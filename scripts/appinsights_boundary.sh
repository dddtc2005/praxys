#!/usr/bin/env bash
set -Eeuo pipefail

readonly BACKEND_APP_SERVICE="trainsight-app"
readonly API_WEBTEST_NAME="wt-praxys-api-health"
readonly SCHEDULED_QUERY_API_VERSION="2026-03-01"
readonly BACKEND_ALERT_NAMES=(
  "praxys-db-health-unhealthy"
  "praxys-feedback-needs-review"
  "praxys-today-latency-regression"
  "praxys-sync-systemic-failures"
  "praxys-connect-systemic-failures"
)

fail() {
  echo "ERROR: $*" >&2
  return 1
}

require_env() {
  local name
  for name in "$@"; do
    [[ -n "${!name:-}" ]] || fail "required environment variable ${name} is empty"
  done
}

ids_equal() {
  local left="${1//$'\r'/}"
  local right="${2//$'\r'/}"
  [[ "${left,,}" == "${right,,}" ]]
}

component_id() {
  az resource show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "$1" \
    --resource-type Microsoft.Insights/components \
    --query id -o tsv
}

load_boundary_resources() {
  require_env \
    AZURE_RESOURCE_GROUP \
    LOG_ANALYTICS_WORKSPACE \
    FRONTEND_APPINSIGHTS_NAME \
    BACKEND_APPINSIGHTS_NAME

  WORKSPACE_ID="$(az monitor log-analytics workspace show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --workspace-name "${LOG_ANALYTICS_WORKSPACE}" \
    --query id -o tsv)"
  FRONTEND_AI_ID="$(component_id "${FRONTEND_APPINSIGHTS_NAME}")"
  BACKEND_AI_ID="$(component_id "${BACKEND_APPINSIGHTS_NAME}")"

  [[ -n "${WORKSPACE_ID}" && -n "${FRONTEND_AI_ID}" && -n "${BACKEND_AI_ID}" ]] ||
    fail "observability resources must exist before deployment"
  ! ids_equal "${FRONTEND_AI_ID}" "${BACKEND_AI_ID}" ||
    fail "frontend and backend Application Insights resources must be distinct"

  local resource_id linked_workspace
  for resource_id in "${FRONTEND_AI_ID}" "${BACKEND_AI_ID}"; do
    linked_workspace="$(az resource show \
      --ids "${resource_id}" \
      --query properties.WorkspaceResourceId -o tsv)"
    ids_equal "${linked_workspace}" "${WORKSPACE_ID}" ||
      fail "${resource_id} is not linked to ${LOG_ANALYTICS_WORKSPACE}"
  done
}

write_github_env() {
  require_env GITHUB_ENV
  printf '%s=%s\n' "$1" "$2" >> "${GITHUB_ENV}"
}

verify_anonymous_ingestion_rejected() {
  local connection_string="$1"
  local instrumentation_key=""
  local ingestion_endpoint=""
  local segment key value

  while IFS= read -r segment; do
    key="${segment%%=*}"
    value="${segment#*=}"
    case "${key}" in
      InstrumentationKey) instrumentation_key="${value}" ;;
      IngestionEndpoint) ingestion_endpoint="${value}" ;;
    esac
  done < <(tr ';' '\n' <<< "${connection_string}")

  [[ -n "${instrumentation_key}" && -n "${ingestion_endpoint}" ]] ||
    fail "backend connection string is missing ingestion routing fields"

  local payload response_file status
  payload="$(jq -cn \
    --arg ikey "${instrumentation_key}" \
    --arg time "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
    '{
      name: "Microsoft.ApplicationInsights.Event",
      time: $time,
      iKey: $ikey,
      data: {
        baseType: "EventData",
        baseData: {
          ver: 2,
          name: "praxys.product_event",
          properties: {
            event_name: "forged_browser_probe",
            source: "deployment-boundary-check"
          }
        }
      }
    }')"
  response_file="$(mktemp)"
  status="$(curl \
    --silent \
    --show-error \
    --output "${response_file}" \
    --write-out "%{http_code}" \
    --header "Content-Type: application/json" \
    --request POST \
    --data "${payload}" \
    "${ingestion_endpoint%/}/v2.1/track")"
  rm -f "${response_file}"

  case "${status}" in
    401|403) return 0 ;;
    *) fail "backend accepted anonymous instrumentation-key ingestion (HTTP ${status})" ;;
  esac
}

scheduled_alert_url() {
  printf 'https://management.azure.com%s?api-version=%s' \
    "$1" "${SCHEDULED_QUERY_API_VERSION}"
}

scheduled_alert_body() {
  local source_json="$1"
  local target_scope="$2"

  jq -S -c \
    --arg scope "${target_scope}" \
    '
      def writable_identity:
        if . == null then null
        else {
          type,
          userAssignedIdentities: (
            if .userAssignedIdentities == null then null
            else (.userAssignedIdentities | with_entries(.value = {}))
            end
          )
        } | with_entries(select(.value != null))
        end;
      {
        location,
        tags,
        kind,
        identity: (.identity | writable_identity),
        properties: (
          .properties
          | del(.createdWithApiVersion)
          | .scopes = [$scope]
        )
      } | with_entries(select(.value != null))
    ' <<< "${source_json}"
}

normalize_scheduled_alert() {
  jq -S -c '
    def writable_identity:
      if . == null then null
      else {
        type,
        userAssignedIdentities: (
          if .userAssignedIdentities == null then null
          else (.userAssignedIdentities | with_entries(.value = {}))
          end
        )
      } | with_entries(select(.value != null))
      end;
    {
      location,
      tags,
      kind,
      identity: (.identity | writable_identity),
      properties: (.properties | del(.createdWithApiVersion))
    } | with_entries(select(.value != null))
  '
}

is_resource_not_found() {
  grep -Eqi 'ResourceNotFound|Not Found|status.?404|HTTP 404' <<< "$1"
}

delete_scheduled_alert() {
  local alert_id="$1"
  local output

  if ! output="$(az rest \
    --method delete \
    --url "$(scheduled_alert_url "${alert_id}")" \
    --output none 2>&1)"; then
    if is_resource_not_found "${output}"; then
      return 0
    fi
    echo "${output}" >&2
    return 1
  fi

  local attempt
  for attempt in {1..10}; do
    if output="$(az rest \
      --method get \
      --url "$(scheduled_alert_url "${alert_id}")" \
      -o json 2>&1)"; then
      sleep 2
      continue
    fi
    if is_resource_not_found "${output}"; then
      return 0
    fi
    echo "${output}" >&2
    return 1
  done

  fail "timed out waiting for scheduled alert deletion: ${alert_id}"
}

recreate_scheduled_alert() {
  local alert_id="$1"
  local source_json="$2"
  local target_scope="$3"
  local body output actual_json expected_normalized actual_normalized

  body="$(scheduled_alert_body "${source_json}" "${target_scope}")"
  delete_scheduled_alert "${alert_id}"

  local attempt
  for attempt in {1..5}; do
    if output="$(az rest \
      --method put \
      --url "$(scheduled_alert_url "${alert_id}")" \
      --headers "Content-Type=application/json" \
      --body "${body}" \
      --output none 2>&1)"; then
      break
    fi
    if [[ "${attempt}" == "5" ]]; then
      echo "${output}" >&2
      return 1
    fi
    sleep "$((attempt * 2))"
  done

  for attempt in {1..10}; do
    if actual_json="$(az rest \
      --method get \
      --url "$(scheduled_alert_url "${alert_id}")" \
      -o json 2>/dev/null)"; then
      break
    fi
    if [[ "${attempt}" == "10" ]]; then
      fail "timed out waiting for scheduled alert recreation: ${alert_id}"
    fi
    sleep 2
  done

  expected_normalized="$(normalize_scheduled_alert <<< "${body}")"
  actual_normalized="$(normalize_scheduled_alert <<< "${actual_json}")"
  if [[ "${actual_normalized}" != "${expected_normalized}" ]]; then
    echo "Expected scheduled alert:" >&2
    jq . <<< "${expected_normalized}" >&2
    echo "Actual scheduled alert:" >&2
    jq . <<< "${actual_normalized}" >&2
    fail "scheduled alert recreation changed behavior: ${alert_id}"
  fi
}

backend_preflight() {
  load_boundary_resources

  az resource update \
    --ids "${BACKEND_AI_ID}" \
    --set \
      properties.DisableLocalAuth=true \
      tags.trustBoundary=backend \
      tags.managedBy=deploy-backend \
    --output none

  local disable_local_auth
  disable_local_auth="$(az resource show \
    --ids "${BACKEND_AI_ID}" \
    --query properties.DisableLocalAuth -o tsv)"
  [[ "${disable_local_auth,,}" == "true" ]] ||
    fail "backend Application Insights local authentication is not disabled"

  local backend_mi_principal publisher_role_count
  backend_mi_principal="$(az webapp identity show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${BACKEND_APP_SERVICE}" \
    --query principalId -o tsv)"
  publisher_role_count="$(az role assignment list \
    --assignee-object-id "${backend_mi_principal}" \
    --scope "${BACKEND_AI_ID}" \
    --query "[?roleDefinitionName=='Monitoring Metrics Publisher'] | length(@)" \
    -o tsv)"
  [[ "${publisher_role_count:-0}" != "0" ]] ||
    fail "${BACKEND_APP_SERVICE} managed identity lacks Monitoring Metrics Publisher on ${BACKEND_APPINSIGHTS_NAME}; see docs/ops/config-and-secrets.md"

  local connection_string
  connection_string="$(az resource show \
    --ids "${BACKEND_AI_ID}" \
    --query properties.ConnectionString -o tsv)"
  [[ -n "${connection_string}" ]] ||
    fail "backend Application Insights connection string is empty"

  verify_anonymous_ingestion_rejected "${connection_string}"

  echo "::add-mask::${connection_string}"
  write_github_env "APPLICATIONINSIGHTS_CONNECTION_STRING" "${connection_string}"
  write_github_env "FRONTEND_APPINSIGHTS_RESOURCE_ID" "${FRONTEND_AI_ID}"
  write_github_env "BACKEND_APPINSIGHTS_RESOURCE_ID" "${BACKEND_AI_ID}"
}

frontend_resolve() {
  load_boundary_resources

  local frontend_local_auth backend_local_auth
  frontend_local_auth="$(az resource show \
    --ids "${FRONTEND_AI_ID}" \
    --query properties.DisableLocalAuth -o tsv)"
  backend_local_auth="$(az resource show \
    --ids "${BACKEND_AI_ID}" \
    --query properties.DisableLocalAuth -o tsv)"
  [[ "${frontend_local_auth,,}" != "true" ]] ||
    fail "frontend Application Insights must allow browser instrumentation-key ingestion"
  [[ "${backend_local_auth,,}" == "true" ]] ||
    fail "backend Application Insights must reject instrumentation-key ingestion"

  az resource update \
    --ids "${FRONTEND_AI_ID}" \
    --set \
      tags.trustBoundary=frontend \
      tags.managedBy=deploy-frontend-appservice \
    --output none

  local connection_string
  connection_string="$(az resource show \
    --ids "${FRONTEND_AI_ID}" \
    --query properties.ConnectionString -o tsv)"
  [[ -n "${connection_string}" ]] ||
    fail "frontend Application Insights connection string is empty"

  echo "::add-mask::${connection_string}"
  write_github_env "VITE_APPINSIGHTS_CONNECTION_STRING" "${connection_string}"
}

telemetry_cutover() {
  local target="$1"
  load_boundary_resources

  local target_ai_id other_ai_id target_connection_string target_name
  case "${target}" in
    backend)
      require_env \
        APPLICATIONINSIGHTS_CONNECTION_STRING \
        FRONTEND_APPINSIGHTS_RESOURCE_ID \
        BACKEND_APPINSIGHTS_RESOURCE_ID
      ids_equal "${FRONTEND_AI_ID}" "${FRONTEND_APPINSIGHTS_RESOURCE_ID}" ||
        fail "frontend Application Insights resource changed after preflight"
      ids_equal "${BACKEND_AI_ID}" "${BACKEND_APPINSIGHTS_RESOURCE_ID}" ||
        fail "backend Application Insights resource changed after preflight"
      target_ai_id="${BACKEND_AI_ID}"
      other_ai_id="${FRONTEND_AI_ID}"
      target_connection_string="${APPLICATIONINSIGHTS_CONNECTION_STRING}"
      target_name="${BACKEND_APPINSIGHTS_NAME}"
      ;;
    frontend)
      target_ai_id="${FRONTEND_AI_ID}"
      other_ai_id="${BACKEND_AI_ID}"
      target_connection_string="$(az resource show \
        --ids "${FRONTEND_AI_ID}" \
        --query properties.ConnectionString -o tsv)"
      [[ -n "${target_connection_string}" ]] ||
        fail "frontend Application Insights connection string is empty"
      target_name="${FRONTEND_APPINSIGHTS_NAME}"
      echo "::add-mask::${target_connection_string}"
      ;;
    *)
      fail "unknown telemetry cutover target: ${target}"
      ;;
  esac

  local old_connection_string
  old_connection_string="$(az webapp config appsettings list \
    --name "${BACKEND_APP_SERVICE}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].value | [0]" \
    -o tsv)"
  [[ -n "${old_connection_string}" ]] &&
    echo "::add-mask::${old_connection_string}"

  local -a alert_ids=()
  local -a old_alert_jsons=()
  local -a old_alert_scopes=()
  local alert_name alert_id alert_json alert_scope scope_count
  for alert_name in "${BACKEND_ALERT_NAMES[@]}"; do
    alert_id="$(az resource show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${alert_name}" \
      --resource-type Microsoft.Insights/scheduledQueryRules \
      --query id -o tsv)"
    alert_json="$(az rest \
      --method get \
      --url "$(scheduled_alert_url "${alert_id}")" \
      -o json | jq -c '.')"
    scope_count="$(jq -r '.properties.scopes | length' <<< "${alert_json}")"
    alert_scope="$(jq -r '.properties.scopes[0]' <<< "${alert_json}")"
    [[ "${scope_count}" == "1" ]] ||
      fail "${alert_name} must have exactly one Application Insights scope"
    if ! ids_equal "${alert_scope}" "${FRONTEND_AI_ID}" &&
       ! ids_equal "${alert_scope}" "${BACKEND_AI_ID}"; then
      fail "${alert_name} has an unexpected scope: ${alert_scope}"
    fi
    alert_ids+=("${alert_id}")
    old_alert_jsons+=("${alert_json}")
    old_alert_scopes+=("${alert_scope}")
  done

  local api_webtest_id old_api_webtest_tags frontend_link_key backend_link_key
  local target_link_key other_link_key
  api_webtest_id="$(az resource show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${API_WEBTEST_NAME}" \
    --resource-type Microsoft.Insights/webtests \
    --query id -o tsv)"
  old_api_webtest_tags="$(az resource show \
    --ids "${api_webtest_id}" \
    --query tags -o json)"
  frontend_link_key="hidden-link:${FRONTEND_AI_ID}"
  backend_link_key="hidden-link:${BACKEND_AI_ID}"
  if [[ "${target}" == "backend" ]]; then
    target_link_key="${backend_link_key}"
    other_link_key="${frontend_link_key}"
  else
    target_link_key="${frontend_link_key}"
    other_link_key="${backend_link_key}"
  fi
  jq -e \
    --arg frontend "${frontend_link_key}" \
    --arg backend "${backend_link_key}" \
    '.[$frontend] == "Resource" or .[$backend] == "Resource"' \
    <<< "${old_api_webtest_tags}" >/dev/null ||
    fail "${API_WEBTEST_NAME} is not linked to either configured component"

  local api_alert_id old_api_alert_json old_api_alert_component
  local -a old_api_alert_scopes=()
  api_alert_id="$(az monitor metrics alert show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${API_WEBTEST_NAME}" \
    --query id -o tsv)"
  old_api_alert_json="$(az monitor metrics alert show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${API_WEBTEST_NAME}" \
    -o json)"
  mapfile -t old_api_alert_scopes < <(
    jq -r '.scopes[]' <<< "${old_api_alert_json}"
  )
  old_api_alert_component="$(
    jq -r '.criteria.componentId' <<< "${old_api_alert_json}"
  )"
  [[ "${#old_api_alert_scopes[@]}" == "2" ]] ||
    fail "${API_WEBTEST_NAME} alert must have exactly two scopes"
  ids_equal "$(
    jq -r '.criteria.webTestId' <<< "${old_api_alert_json}"
  )" "${api_webtest_id}" ||
    fail "${API_WEBTEST_NAME} alert criteria points to a different web test"
  if ! ids_equal "${old_api_alert_component}" "${FRONTEND_AI_ID}" &&
     ! ids_equal "${old_api_alert_component}" "${BACKEND_AI_ID}"; then
    fail "${API_WEBTEST_NAME} alert has an unexpected component"
  fi
  local found_webtest=false found_component=false scope
  for scope in "${old_api_alert_scopes[@]}"; do
    ids_equal "${scope}" "${api_webtest_id}" && found_webtest=true
    ids_equal "${scope}" "${old_api_alert_component}" && found_component=true
  done
  [[ "${found_webtest}" == "true" && "${found_component}" == "true" ]] ||
    fail "${API_WEBTEST_NAME} alert scopes do not match its criteria"

  rollback_cutover() {
    local exit_code=$?
    local rollback_failed=false
    trap - ERR
    set +e
    echo "Telemetry cutover failed; restoring the prior routing and alert scopes" >&2

    if [[ -n "${old_connection_string}" ]]; then
      if ! az webapp config appsettings set \
        --name "${BACKEND_APP_SERVICE}" \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --settings \
          APPLICATIONINSIGHTS_CONNECTION_STRING="${old_connection_string}" \
        --output none; then
        rollback_failed=true
      fi
    else
      if ! az webapp config appsettings delete \
        --name "${BACKEND_APP_SERVICE}" \
        --resource-group "${AZURE_RESOURCE_GROUP}" \
        --setting-names APPLICATIONINSIGHTS_CONNECTION_STRING \
        --output none; then
        rollback_failed=true
      fi
    fi

    local index
    for index in "${!alert_ids[@]}"; do
      if ! recreate_scheduled_alert \
        "${alert_ids[$index]}" \
        "${old_alert_jsons[$index]}" \
        "${old_alert_scopes[$index]}"; then
        rollback_failed=true
      fi
    done

    if ! az rest \
      --method patch \
      --url "https://management.azure.com${api_webtest_id}?api-version=2022-06-15" \
      --headers "Content-Type=application/json" \
      --body "$(jq -cn \
        --argjson tags "${old_api_webtest_tags}" \
        '{tags: $tags}')" \
      --output none; then
      rollback_failed=true
    fi
    if ! az resource update \
      --ids "${api_alert_id}" \
      --set \
        "properties.scopes[0]=${old_api_alert_scopes[0]}" \
        "properties.scopes[1]=${old_api_alert_scopes[1]}" \
        "properties.criteria.componentId=${old_api_alert_component}" \
      --output none; then
      rollback_failed=true
    fi

    local restored_connection_string
    if ! restored_connection_string="$(az webapp config appsettings list \
      --name "${BACKEND_APP_SERVICE}" \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].value | [0]" \
      -o tsv)"; then
      rollback_failed=true
    elif [[ "${restored_connection_string}" != "${old_connection_string}" ]]; then
      echo "Rollback verification failed for backend telemetry routing" >&2
      rollback_failed=true
    fi

    local restored_webtest_tags expected_webtest_tags
    expected_webtest_tags="$(jq -S -c . <<< "${old_api_webtest_tags}")"
    if ! restored_webtest_tags="$(az resource show \
      --ids "${api_webtest_id}" \
      --query tags -o json | jq -S -c '.')"; then
      rollback_failed=true
    elif [[ "${restored_webtest_tags}" != "${expected_webtest_tags}" ]]; then
      echo "Rollback verification failed for ${API_WEBTEST_NAME} hidden-link" >&2
      rollback_failed=true
    fi

    local restored_api_alert_json restored_api_component
    local -a restored_api_scopes=()
    if ! restored_api_alert_json="$(az monitor metrics alert show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${API_WEBTEST_NAME}" \
      -o json)"; then
      rollback_failed=true
    else
      restored_api_component="$(
        jq -r '.criteria.componentId' <<< "${restored_api_alert_json}"
      )"
      mapfile -t restored_api_scopes < <(
        jq -r '.scopes[]' <<< "${restored_api_alert_json}"
      )
      if [[ "${#restored_api_scopes[@]}" != "2" ]] ||
         ! ids_equal "${restored_api_scopes[0]}" "${old_api_alert_scopes[0]}" ||
         ! ids_equal "${restored_api_scopes[1]}" "${old_api_alert_scopes[1]}" ||
         ! ids_equal "${restored_api_component}" "${old_api_alert_component}"; then
        echo "Rollback verification failed for ${API_WEBTEST_NAME} metric alert" >&2
        rollback_failed=true
      fi
    fi

    if [[ "${rollback_failed}" == "true" ]]; then
      echo "CRITICAL: telemetry rollback was incomplete; inspect App Service and alert scopes immediately" >&2
      exit 70
    fi
    exit "${exit_code}"
  }
  trap rollback_cutover ERR

  az webapp config appsettings set \
    --name "${BACKEND_APP_SERVICE}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --settings \
      APPLICATIONINSIGHTS_CONNECTION_STRING="${target_connection_string}" \
    --output none

  local index
  for index in "${!alert_ids[@]}"; do
    recreate_scheduled_alert \
      "${alert_ids[$index]}" \
      "${old_alert_jsons[$index]}" \
      "${target_ai_id}"
  done

  local new_api_webtest_tags
  new_api_webtest_tags="$(jq -c \
    --arg frontend "${frontend_link_key}" \
    --arg backend "${backend_link_key}" \
    --arg target "${target_link_key}" \
    'del(.[$frontend], .[$backend]) | .[$target] = "Resource"' \
    <<< "${old_api_webtest_tags}")"
  az rest \
    --method patch \
    --url "https://management.azure.com${api_webtest_id}?api-version=2022-06-15" \
    --headers "Content-Type=application/json" \
    --body "$(jq -cn \
      --argjson tags "${new_api_webtest_tags}" \
      '{tags: $tags}')" \
    --output none
  az resource update \
    --ids "${api_alert_id}" \
    --set \
      "properties.scopes[0]=${api_webtest_id}" \
      "properties.scopes[1]=${target_ai_id}" \
      "properties.criteria.componentId=${target_ai_id}" \
    --output none

  local live_connection_string
  live_connection_string="$(az webapp config appsettings list \
    --name "${BACKEND_APP_SERVICE}" \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --query "[?name=='APPLICATIONINSIGHTS_CONNECTION_STRING'].value | [0]" \
    -o tsv)"
  [[ "${live_connection_string}" == "${target_connection_string}" ]] ||
    fail "backend App Service telemetry routing does not match ${target_name}"

  for alert_name in "${BACKEND_ALERT_NAMES[@]}"; do
    alert_id="$(az resource show \
      --resource-group "${AZURE_RESOURCE_GROUP}" \
      --name "${alert_name}" \
      --resource-type Microsoft.Insights/scheduledQueryRules \
      --query id -o tsv)"
    alert_scope="$(az rest \
      --method get \
      --url "$(scheduled_alert_url "${alert_id}")" \
      --query "properties.scopes[0]" -o tsv)"
    ids_equal "${alert_scope}" "${target_ai_id}" ||
      fail "${alert_name} is not scoped to ${target_name}"
  done

  az resource show \
    --ids "${api_webtest_id}" \
    --query tags -o json |
    jq -e \
      --arg target "${target_link_key}" \
      --arg other "${other_link_key}" \
      '.[$target] == "Resource" and has($other) == false' >/dev/null ||
    fail "${API_WEBTEST_NAME} hidden-link did not migrate cleanly"

  local live_api_alert_json
  live_api_alert_json="$(az monitor metrics alert show \
    --resource-group "${AZURE_RESOURCE_GROUP}" \
    --name "${API_WEBTEST_NAME}" \
    -o json)"
  jq -e \
    --arg webtest "${api_webtest_id}" \
    --arg target "${target_ai_id}" \
    --arg other "${other_ai_id}" \
    '
      def lower: ascii_downcase;
      (.criteria.webTestId | lower) == ($webtest | lower)
      and (.criteria.componentId | lower) == ($target | lower)
      and (.scopes | length) == 2
      and any(.scopes[]; (lower == ($webtest | lower)))
      and any(.scopes[]; (lower == ($target | lower)))
      and all(.scopes[]; (lower != ($other | lower)))
    ' <<< "${live_api_alert_json}" >/dev/null ||
    fail "${API_WEBTEST_NAME} alert did not migrate cleanly"

  trap - ERR
}

case "${1:-}" in
  backend-preflight) backend_preflight ;;
  backend-cutover) telemetry_cutover backend ;;
  rollback-to-frontend) telemetry_cutover frontend ;;
  frontend-resolve) frontend_resolve ;;
  *)
    echo "Usage: $0 {backend-preflight|backend-cutover|rollback-to-frontend|frontend-resolve}" >&2
    exit 2
    ;;
esac
