"""Finite local QA origin policy; never establishes a device or reverse mapping."""
import re
MODE_KEY = 'CASEOPS_MOBILE_ANDROID_TRANSPORT_MODE'
MODES = ('emulator', 'usb-reverse')

def port(value):
    if isinstance(value, str):
        assert re.fullmatch(r'[1-9][0-9]{3,4}', value), 'Explicit unprivileged port required'
        value = int(value)
    assert type(value) is int and 1024 <= value <= 65535, 'Explicit unprivileged port required'
    return str(value)

def policy(config, requested_platform=None, requested_mode=None):
    assert isinstance(config, dict), 'Fixture config object required'
    assert all(not isinstance(key, str) or key.upper() != MODE_KEY or key == MODE_KEY for key in config), 'Exact Android transport mode key required'
    platform = config.get('CASEOPS_MOBILE_PLATFORM', 'android')
    assert platform in ('android', 'ios'), 'Unsupported fixture platform'
    if requested_platform is not None:
        assert requested_platform in ('android', 'ios') and requested_platform == platform, 'Fixture platform mismatch'
    if platform == 'ios':
        assert MODE_KEY not in config and requested_mode is None, 'Android transport mode is Android only'
        mode = None
    else:
        mode = config.get(MODE_KEY, 'emulator')
        assert type(mode) is str and mode in MODES, 'Unsupported Android transport mode'
        assert requested_mode is None or type(requested_mode) is str and requested_mode == mode, 'Android transport mode mismatch'
    api_port = port(config.get('CASEOPS_MOBILE_API_PORT', 8443))
    web_port = port(config.get('CASEOPS_MOBILE_WEB_PORT', 3443))
    assert api_port != web_port, 'API and web ports must differ'
    host = '127.0.0.1' if platform == 'ios' or mode == 'usb-reverse' else '10.0.2.2'
    origins = {'CASEOPS_MOBILE_API_ORIGIN': f'https://{host}:{api_port}', 'CASEOPS_MOBILE_WEB_ORIGIN': f'https://{host}:{web_port}'}
    assert all(key not in config or config[key] == value for key, value in origins.items()), 'Fixture origin differs from platform transport policy'
    return {'platform': platform, 'mode': mode, 'apiPort': api_port, 'webPort': web_port, 'apiOrigin': origins['CASEOPS_MOBILE_API_ORIGIN'], 'webOrigin': origins['CASEOPS_MOBILE_WEB_ORIGIN']}

def fields(config):
    value = policy(config)
    return {'androidTransportMode': value['mode']} if MODE_KEY in config else {}

def witness(config, value, *, require_api=True):
    expected = policy(config)
    assert isinstance(value, dict) and value.get('platform', 'android') == expected['platform'], 'Fixture witness platform mismatch'
    if expected['platform'] == 'ios':
        assert 'androidTransportMode' not in value, 'Android transport mode is Android only'
    else:
        assert value.get('androidTransportMode', 'emulator') == expected['mode'], 'Fixture witness Android transport mismatch'
    assert value.get('webOrigin') == expected['webOrigin'], 'Fixture witness web origin mismatch'
    if require_api or expected['mode'] == 'usb-reverse':
        assert value.get('apiOrigin') == expected['apiOrigin'], 'Fixture witness API origin mismatch'
    return expected
