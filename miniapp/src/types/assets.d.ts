// Ambient module declarations for static image imports so TypeScript
// accepts the bundler-rewritten URLs. Missing-file errors are deferred
// to bundle time — acceptable trade-off for the convenience.

declare module '*.jpg' {
  const src: string;
  export default src;
}

declare module '*.jpeg' {
  const src: string;
  export default src;
}

declare module '*.png' {
  const src: string;
  export default src;
}

declare module '*.svg' {
  const src: string;
  export default src;
}
