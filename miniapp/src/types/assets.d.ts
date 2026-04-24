// Ambient module declarations for static image imports, so Taro/webpack
// can rewrite `import img from '…/foo.jpg'` into the bundled asset URL
// while TypeScript still typechecks. Matches the shape used by Taro's
// own default template (node_modules/@tarojs/cli/templates/.../types/global.d.ts).

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
