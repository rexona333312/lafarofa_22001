const path = require('node:path');
const {Config} = require('@remotion/cli/config');

Config.overrideWebpackConfig(config => ({
  ...config,
  resolve: {...config.resolve, alias: {...config.resolve?.alias, '@': path.resolve(process.cwd(), 'src')}},
}));
