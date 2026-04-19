// Babel config for Taro mini-program build.
// babel-preset-taro auto-selects the right plugins based on the
// compilation target (weapp, alipay, etc.) — we stay on the default.
module.exports = {
  presets: [
    ['taro', { framework: 'react', ts: true }],
  ],
};
