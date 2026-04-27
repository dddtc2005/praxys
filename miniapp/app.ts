// Root app lifecycle. The login page owns the auth flow on its own onLoad,
// so onLaunch deliberately does nothing — keeping startup deterministic
// regardless of which page the user lands on.
App({
  onLaunch() {},
});
