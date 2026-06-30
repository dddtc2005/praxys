import { useState } from "react";
import { Link } from "react-router-dom";
import { useAuth } from "@/hooks/useAuth";
import { useLocale } from "@/contexts/LocaleContext";
import { TERMS_VERSION, EFFECTIVE_DATE } from "@/lib/legal";

/**
 * Blocking re-consent modal shown when the signed-in user's accepted Terms/EULA
 * version is stale (or null). Mirrors the registration agree UI: a checkbox plus
 * links to the full Terms and Privacy. The app stays gated until the user
 * acknowledges, which stamps the live TERMS_VERSION via POST /api/me/accept-terms.
 *
 * The modal follows the app locale (set globally from the user's saved language
 * preference / browser detection). It deliberately has no own language toggle:
 * LocaleSync owns the authed-area locale and would immediately revert a
 * local-only switch back to config.language. Readers who want the other
 * language can open the full Terms / Privacy pages, which carry their own toggle.
 */
export default function TermsGate() {
  const { acceptTerms } = useAuth();
  const { locale } = useLocale();
  const zh = locale === "zh";
  const [agreed, setAgreed] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleAccept = async () => {
    if (!agreed) return;
    setSubmitting(true);
    setError(null);
    const ok = await acceptTerms();
    if (!ok) {
      setError(zh ? "提交失败，请重试。" : "Could not save — please try again.");
      setSubmitting(false);
    }
    // On success the gate unmounts as termsCurrent flips true.
  };

  return (
    <div className="fixed inset-0 z-[100] flex items-center justify-center bg-background/80 backdrop-blur-sm p-4">
      <div className="w-full max-w-md rounded-lg border border-border bg-card p-6 shadow-lg">
        <h2 className="text-lg font-semibold">
          {zh ? "条款已更新" : "Updated Terms"}
        </h2>
        <p className="mt-1 text-sm text-muted-foreground font-data">
          v{TERMS_VERSION} · {zh ? "生效日期 " : "Effective "}{EFFECTIVE_DATE}
        </p>
        <p className="mt-4 text-sm leading-relaxed text-muted-foreground">
          {zh
            ? "我们更新了服务条款与隐私政策。请阅读并同意后继续使用。"
            : "We've updated our Terms and Privacy Policy. Please review and accept to continue."}
        </p>

        <label className="mt-5 flex items-start gap-2 text-sm text-muted-foreground">
          <input
            type="checkbox"
            checked={agreed}
            onChange={(e) => setAgreed(e.target.checked)}
            disabled={submitting}
            className="mt-0.5 flex-none"
          />
          <span>
            {zh ? "我同意" : "I agree to the"}{" "}
            <Link to="/terms" target="_blank" className="text-primary hover:underline">
              {zh ? "服务条款" : "Terms of Service"}
            </Link>{" "}
            {zh ? "与" : "and"}{" "}
            <Link to="/privacy" target="_blank" className="text-primary hover:underline">
              {zh ? "隐私政策" : "Privacy Policy"}
            </Link>
            {zh ? "。" : "."}
          </span>
        </label>

        {error && <p className="mt-3 text-sm text-destructive">{error}</p>}

        <button
          type="button"
          onClick={handleAccept}
          disabled={!agreed || submitting}
          className="mt-6 w-full rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:opacity-50"
        >
          {submitting
            ? (zh ? "保存中…" : "Saving…")
            : (zh ? "同意并继续" : "Accept and continue")}
        </button>
      </div>
    </div>
  );
}
