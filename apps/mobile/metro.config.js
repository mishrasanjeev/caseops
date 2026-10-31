const path = require('node:path');
const { getDefaultConfig } = require('expo/metro-config');
const config = getDefaultConfig(__dirname);
// The public callback policy is the single shared browser/native implementation.
// No Node-only config reader is imported by the mobile runtime.
config.watchFolders = [...new Set([...config.watchFolders, path.resolve(__dirname, '../web/lib')])];
module.exports = config;
