'use strict';
const { withInfoPlist } = require('expo/config-plugins');

// An Android-only production link input has no iOS application identity:
// refuse an iOS native project rather than build the development bundle.
function withIosLinkRequired(config) {
  return withInfoPlist(config, () => {
    throw new Error('IOS_NATIVE_LINK_CONFIG_REQUIRED');
  });
}
module.exports = withIosLinkRequired;
