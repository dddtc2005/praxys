/**
 * Taro build configuration.
 * Entry point is src/app; output goes to dist/.
 * Environment-specific overrides are defined in dev.ts / prod.ts.
 */
import path from 'path';

import type { UserConfigExport } from '@tarojs/cli';

const config: UserConfigExport = {
  projectName: 'trainsight-miniapp',
  date: '2026-04-18',
  designWidth: 750,
  deviceRatio: {
    640: 2.34 / 2,
    750: 1,
    828: 1.81 / 2,
  },
  sourceRoot: 'src',
  outputRoot: 'dist',
  plugins: [],
  defineConstants: {},
  copy: {
    patterns: [],
    options: {},
  },
  framework: 'react',
  compiler: {
    type: 'webpack5',
    prebundle: { enable: false },
  },
  cache: { enable: false },
  mini: {
    postcss: {
      pxtransform: { enable: true, config: {} },
      url: { enable: true, config: { limit: 1024 } },
      cssModules: { enable: false, config: { namingPattern: 'module', generateScopedName: '[name]__[local]___[hash:base64:5]' } },
    },
  },
  h5: {
    publicPath: '/',
    staticDirectory: 'static',
    postcss: {
      autoprefixer: { enable: true, config: {} },
      cssModules: { enable: false, config: { namingPattern: 'module', generateScopedName: '[name]__[local]___[hash:base64:5]' } },
    },
  },
  alias: {
    '@': path.resolve(__dirname, '..', 'src'),
  },
};

export default (merge: (...args: any[]) => UserConfigExport) => {
  if (process.env.NODE_ENV === 'development') {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    return merge({}, config, require('./dev').default);
  }
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  return merge({}, config, require('./prod').default);
};
