# Actual pinned Ruby/OpenURI/TLS contract; no minitest gem, SDK mutation or external request.
require 'json'
require 'digest'
require 'openssl'
require 'socket'
require 'uri'
require 'timeout'
require 'thread'
def check(value, code)
  raise code unless value
end
def held(ref, limit = 1_048_576)
  file = ref.fetch('path'); size = ref.fetch('sizeBytes'); pin = ref.fetch('sha256')
  check(File.realpath(file) == file && size.is_a?(Integer) && size.between?(1, limit), 'TEST_SOURCE_REFERENCE')
  File.open(file, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |input|
    frame = ->(s) { [s.dev, s.ino, s.mode, s.uid, s.gid, s.nlink, s.size, s.mtime.to_r, s.ctime.to_r] }
    first = input.stat
    check(first.file? && first.nlink == 1 && [0, Process.uid].include?(first.uid) && (first.mode & 0o022).zero? && first.size == size && frame.call(first) == frame.call(File.lstat(file)), 'TEST_SOURCE_IDENTITY')
    bytes = input.read(size + 1)
    check(bytes.bytesize == size && Digest::SHA256.hexdigest(bytes) == pin && frame.call(first) == frame.call(input.stat) && frame.call(first) == frame.call(File.lstat(file)), 'TEST_SOURCE_PIN')
    bytes
  end
end
def exclusive(file, bytes)
  File.open(file, File::WRONLY | File::CREAT | File::EXCL | File::NOFOLLOW, 0o600) { |f| f.write(bytes); f.flush; f.fsync }
end
def certificate(key, name, issuer = nil, issuer_key = nil, ip = nil)
  cert = OpenSSL::X509::Certificate.new; cert.version = 2; cert.serial = Random.rand(1 << 120) + 1
  cert.subject = OpenSSL::X509::Name.parse('/CN=' + name); cert.issuer = issuer ? issuer.subject : cert.subject
  cert.public_key = key; cert.not_before = Time.now - 60; cert.not_after = Time.now + 3600
  extension = OpenSSL::X509::ExtensionFactory.new; extension.subject_certificate = cert; extension.issuer_certificate = issuer || cert
  cert.add_extension(extension.create_extension('basicConstraints', issuer ? 'CA:FALSE' : 'CA:TRUE', true))
  cert.add_extension(extension.create_extension('keyUsage', issuer ? 'digitalSignature' : 'keyCertSign,cRLSign', true))
  if issuer
    cert.add_extension(extension.create_extension('extendedKeyUsage', 'serverAuth'))
    cert.add_extension(extension.create_extension('subjectAltName', 'IP:' + ip))
  end
  cert.sign(issuer_key || key, OpenSSL::Digest.new('SHA256')); cert
end
class FixtureServer
  attr_reader :port
  def initialize(cert, key, deadline)
    @tcp = TCPServer.new('127.0.0.1', 0); @port = @tcp.addr[1]; @deadline = deadline; @alive = true
    @rows = []; @lock = Mutex.new; @retry = 0
    context = OpenSSL::SSL::SSLContext.new; context.cert = cert; context.key = key; context.min_version = OpenSSL::SSL::TLS1_2_VERSION
    @ssl = OpenSSL::SSL::SSLServer.new(@tcp, context)
    @thread = Thread.new do
      while @alive && Process.clock_gettime(Process::CLOCK_MONOTONIC) < @deadline
        client = nil
        begin
          client = Timeout.timeout(2) { @ssl.accept }
          first = Timeout.timeout(2) { client.gets }
          next if first.nil?
          check(first.bytesize <= 4096, 'TEST_REQUEST_BOUND'); parts = first.split(' '); check(parts[0] == 'GET', 'TEST_GET_REQUIRED')
          headers = {}; consumed = first.bytesize
          loop do
            line = Timeout.timeout(2) { client.gets }; check(line && (consumed += line.bytesize) <= 16384, 'TEST_HEADERS_BOUND')
            break if line == "\r\n"
            name, value = line.split(':', 2); check(value, 'TEST_HEADER_SHAPE'); headers[name.downcase] = value.strip
          end
          path = parts[1]; @lock.synchronize { @rows << { 'path' => path, 'marker' => headers['x-caseops-automated-test'] } }
          status = 200; body = 'ok'; extra = ''
          if path == '/error'; status = 503; body = 'fixture-error'
          elsif path == '/retry'; @retry += 1; status = 503 if @retry == 1
          elsif path == '/redirect'; status = 302; extra = "Location: https://127.0.0.1:#{@port}/ok\r\n"
          end
          client.write("HTTP/1.1 #{status} Fixture\r\nContent-Length: #{body.bytesize}\r\n#{extra}Connection: close\r\n\r\n#{body}")
        rescue OpenSSL::SSL::SSLError, IOError, SystemCallError, Timeout::Error
          # Expected negative certificate/empty-request paths do not fabricate a GET.
        ensure
          client&.close rescue nil
        end
      end
    end
  end
  def rows; @lock.synchronize { @rows.map(&:dup) }; end
  def stop
    @alive = false; @tcp.close rescue nil; @thread.join(2); check(!@thread.alive?, 'TEST_SERVER_THREAD_UNCLOSED')
  end
end
CASE_IDS = %w[
  OPENURI-01-default-real-tls
  OPENURI-02-unknown-direct-store
  OPENURI-03-custom-ca-file
  OPENURI-04-custom-ca-directory
  OPENURI-05-unsafe-verify
  OPENURI-06-unsafe-version
  OPENURI-07-proxy
  OPENURI-08-http
  OPENURI-09-real-hostname-mismatch
  OPENURI-10-real-unknown-ca
  OPENURI-11-nested-success-restoration
  OPENURI-12-nested-rejection-restoration
  OPENURI-13-http-error-restoration
  OPENURI-14-explicit-retry-marker
  OPENURI-15-redirect-marker
  OPENURI-16-fiber-isolation
  OPENURI-17-thread-isolation
  OPENURI-18-stale-receipt
  OPENURI-19-direct-net-http
  OPENURI-20-marker-override
  OPENURI-21-http-identity
  OPENURI-22-explicit-peer
  OPENURI-23-client-auth-refused
  OPENURI-24-error-identity
  OPENURI-25-return-identity
].freeze
if ARGV == ['--list']
  puts JSON.generate(CASE_IDS); exit(0)
end
check(ARGV.length == 3, 'TEST_CONFIG_ARGUMENTS')
config = JSON.parse(held({ 'path' => ARGV[0], 'sha256' => ARGV[1], 'sizeBytes' => Integer(ARGV[2]) }))
work = config.fetch('work'); stat = File.lstat(work)
check(File.realpath(work) == work && stat.directory? && !stat.symlink? && stat.uid == Process.uid && (stat.mode & 0o777) == 0o700 && Dir.children(work).empty?, 'TEST_OWNED_EMPTY_ROOT')
deadline = Process.clock_gettime(Process::CLOCK_MONOTONIC) + [(config.fetch('deadlineEpochMs') - (Time.now.to_f * 1000).to_i) / 1000.0, 30].min
check(deadline > Process.clock_gettime(Process::CLOCK_MONOTONIC), 'TEST_DEADLINE')
source = held(config.fetch('source'), 32768); base = held(config.fetch('baseBundle'))
key = OpenSSL::PKey::EC.generate('prime256v1'); ca = certificate(key, 'CaseOps owned loopback QA')
server_key = OpenSSL::PKey::EC.generate('prime256v1'); server_cert = certificate(server_key, 'owned-loopback', ca, key, '127.0.0.1')
wrong_key = OpenSSL::PKey::EC.generate('prime256v1'); wrong_cert = certificate(wrong_key, 'wrong-host', ca, key, '127.0.0.2')
foreign_key = OpenSSL::PKey::EC.generate('prime256v1'); foreign_ca = certificate(foreign_key, 'CaseOps foreign QA')
foreign_server_key = OpenSSL::PKey::EC.generate('prime256v1'); foreign_cert = certificate(foreign_server_key, 'untrusted-loopback', foreign_ca, foreign_key, '127.0.0.1')
%w[home empty].each { |name| Dir.mkdir(File.join(work, name), 0o700) }
bundle_file = File.join(work, 'ruby189-test.pem'); bundle = base + "\n" + ca.to_pem; exclusive(bundle_file, bundle)
foreign_file = File.join(work, 'foreign-ca.pem'); exclusive(foreign_file, foreign_ca.to_pem)
policy = { 'bundle' => { 'path' => bundle_file, 'sha256' => Digest::SHA256.hexdigest(bundle), 'sizeBytes' => bundle.bytesize }, 'empty' => File.join(work, 'empty'), 'fixtureSha256' => Digest::SHA256.hexdigest(ca.to_der), 'home' => File.join(work, 'home'), 'podHome' => config.fetch('podHome'), 'rubyGems' => config.fetch('rubyGems') }
ENV['HOME'] = policy['home']; ENV['CURL_HOME'] = policy['home']; ENV['GEM_HOME'] = policy['podHome']; ENV['GEM_PATH'] = [policy['podHome'], policy['rubyGems']].join(':'); ENV['SSL_CERT_FILE'] = bundle_file; ENV['SSL_CERT_DIR'] = policy['empty']; ENV['CASEOPS_IOS_PODS_TLS_POLICY'] = JSON.generate(policy)
%w[NODE_OPTIONS NODE_EXTRA_CA_CERTS NODE_USE_SYSTEM_CA RUBYOPT RUBYLIB OPENSSL_CONF OPENSSL_CONF_INCLUDE HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy CURL_CA_BUNDLE].each { |name| ENV.delete(name) }
eval(source, TOPLEVEL_BINDING, config.fetch('source').fetch('path'), 1)
CaseopsIosPods.admit!
servers = []; failures = 0; reports = []; $caseops_connects = 0; $caseops_allowed_ports = []
begin
  good = FixtureServer.new(server_cert, server_key, deadline); servers << good
  wrong = FixtureServer.new(wrong_cert, wrong_key, deadline); servers << wrong
  foreign = FixtureServer.new(foreign_cert, foreign_server_key, deadline); servers << foreign
  $caseops_allowed_ports = servers.map(&:port)
  Net::HTTP.prepend(Module.new do
    def connect
      $caseops_connects += 1
      check(address == '127.0.0.1' && $caseops_allowed_ports.include?(port), 'TEST_NONLOCAL_TRANSPORT')
      super
    end
  end)
  url = ->(server, path = '/ok') { 'https://127.0.0.1:' + server.port.to_s + path }
  read = ->(server = good, path = '/ok', options = {}) { OpenURI.open_uri(url.call(server, path), { open_timeout: 2, read_timeout: 2 }.merge(options)) { |io| io.read } }
  refusal = lambda do |code, &block|
    caught = false
    begin; block.call
    rescue RuntimeError => error; check(error.message == code, 'TEST_WRONG_POLICY_ERROR'); caught = true
    end
    check(caught, 'TEST_EXPECTED_POLICY_REFUSAL')
  end
  ssl_failure = lambda do |&block|
    caught = false
    begin; block.call
    rescue OpenSSL::SSL::SSLError; caught = true
    end
    check(caught, 'TEST_EXPECTED_TLS_REFUSAL')
  end
  unknown = lambda do
    http = Net::HTTP.new('127.0.0.1', good.port, nil); http.use_ssl = true
    store = OpenSSL::X509::Store.new; store.add_cert(ca); http.cert_store = store
    http.open_timeout = http.read_timeout = http.write_timeout = 2
    http.start { |client| client.get('/ok') }
  end
  row_count = -> { servers.sum { |server| server.rows.length } }
  cases = [
    -> { value = read.call; check(value == 'ok', 'TEST_BODY') },
    -> { n = $caseops_connects; refusal.call('IOS_PODS_NET_HTTP_STORE_REFUSED') { unknown.call }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = $caseops_connects; refusal.call('IOS_PODS_OPEN_URI_DEFAULT_CA_REQUIRED') { read.call(good, '/ok', ssl_ca_cert: foreign_file) }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = $caseops_connects; refusal.call('IOS_PODS_OPEN_URI_DEFAULT_CA_REQUIRED') { read.call(good, '/ok', ssl_ca_cert: policy['empty']) }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = $caseops_connects; unsafe_mode = OpenSSL::SSL::VERIFY_NONE; refusal.call('IOS_PODS_NET_HTTP_VERIFY_REQUIRED') { read.call(good, '/ok', ssl_verify_mode: unsafe_mode) }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = $caseops_connects; refusal.call('IOS_PODS_OPEN_URI_DEFAULT_CA_REQUIRED') { read.call(good, '/ok', ssl_min_version: OpenSSL::SSL::TLS1_VERSION) }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = $caseops_connects; refusal.call('IOS_PODS_OPEN_URI_HTTPS_REQUIRED') { read.call(good, '/ok', proxy: 'http://127.0.0.1:9') }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = $caseops_connects; refusal.call('IOS_PODS_OPEN_URI_HTTPS_REQUIRED') { OpenURI.open_uri('http://127.0.0.1:' + good.port.to_s + '/ok') }; check($caseops_connects == n, 'TEST_REJECTED_CONNECT') },
    -> { n = row_count.call; ssl_failure.call { read.call(wrong) }; check(row_count.call == n, 'TEST_UNVERIFIED_HTTP_SENT') },
    -> { n = row_count.call; ssl_failure.call { read.call(foreign) }; check(row_count.call == n, 'TEST_UNVERIFIED_HTTP_SENT') },
    -> { seen = false; value = read.call(good, '/ok', content_length_proc: ->(_length) { outer = CaseopsIosPods.current_open_uri_profile; check(outer && outer.active, 'TEST_OUTER_PROFILE'); nested = read.call; check(nested == 'ok', 'TEST_NESTED_BODY'); check(CaseopsIosPods.current_open_uri_profile.equal?(outer), 'TEST_NESTED_RESTORE'); seen = true }); check(value == 'ok' && seen, 'TEST_NESTED_UNREACHED') },
    -> { seen = false; value = read.call(good, '/ok', content_length_proc: ->(_length) { outer = CaseopsIosPods.current_open_uri_profile; n = $caseops_connects; refusal.call('IOS_PODS_OPEN_URI_DEFAULT_CA_REQUIRED') { read.call(good, '/ok', ssl_ca_cert: foreign_file) }; check(CaseopsIosPods.current_open_uri_profile.equal?(outer) && $caseops_connects == n, 'TEST_REJECTION_RESTORE'); seen = true }); check(value == 'ok' && seen, 'TEST_NESTED_UNREACHED') },
    -> { n = row_count.call; caught = false; begin; read.call(good, '/error'); rescue OpenURI::HTTPError; caught = true; end; check(caught && row_count.call == n + 1, 'TEST_HTTP_ERROR_COUNT') },
    -> { n = row_count.call; caught = false; begin; read.call(good, '/retry'); rescue OpenURI::HTTPError; caught = true; end; value = read.call(good, '/retry'); check(caught && value == 'ok' && row_count.call == n + 2, 'TEST_EXPLICIT_RETRY') },
    -> { n = row_count.call; value = read.call(good, '/redirect'); check(value == 'ok' && row_count.call == n + 2, 'TEST_REDIRECT_COUNT') },
    -> { seen = false; read.call(good, '/ok', content_length_proc: ->(_length) { outer = CaseopsIosPods.current_open_uri_profile; Fiber.new { check(CaseopsIosPods.current_open_uri_profile.nil?, 'TEST_FIBER_CONTEXT'); refusal.call('IOS_PODS_NET_HTTP_STORE_REFUSED') { unknown.call } }.resume; check(CaseopsIosPods.current_open_uri_profile.equal?(outer), 'TEST_FIBER_RESTORE'); seen = true }); check(seen, 'TEST_FIBER_UNREACHED') },
    -> { seen = false; read.call(good, '/ok', content_length_proc: ->(_length) { outer = CaseopsIosPods.current_open_uri_profile; child = Thread.new { check(CaseopsIosPods.current_open_uri_profile.nil?, 'TEST_THREAD_CONTEXT'); refusal.call('IOS_PODS_NET_HTTP_STORE_REFUSED') { unknown.call } }; joined = child.join(2); check(joined, 'TEST_THREAD_UNCLOSED'); child.value; check(CaseopsIosPods.current_open_uri_profile.equal?(outer), 'TEST_THREAD_RESTORE'); seen = true }); check(seen, 'TEST_THREAD_UNREACHED') },
    -> { stale = nil; read.call(good, '/ok', content_length_proc: ->(_length) { stale = CaseopsIosPods.current_open_uri_profile }); check(stale && !stale.active && CaseopsIosPods.current_open_uri_profile.nil?, 'TEST_STALE_PROFILE'); stale.http.cert_store = stale.store; n = $caseops_connects; begin; Thread.current[CaseopsIosPods::OPEN_URI_PROFILE_KEY] = stale; refusal.call('IOS_PODS_NET_HTTP_STORE_REFUSED') { stale.http.start { |http| http.get('/ok') } }; check($caseops_connects == n, 'TEST_STALE_CONNECT'); ensure; Thread.current[CaseopsIosPods::OPEN_URI_PROFILE_KEY] = nil; end },
    -> { response = Net::HTTP.start('127.0.0.1', good.port, nil, nil, nil, nil, use_ssl: true, open_timeout: 2, read_timeout: 2, write_timeout: 2) { |http| http.get('/ok') }; check(response.is_a?(Net::HTTPSuccess) && response.body == 'ok', 'TEST_DIRECT_HTTP') },
    -> { n = row_count.call; refusal.call('IOS_PODS_MARKER') { read.call(good, '/ok', 'X-CaseOps-Automated-Test' => 'CONTRADICTORY-SYNTHETIC') }; check(row_count.call == n, 'TEST_MARKER_DISPATCH') },
    -> { seen = false; read.call(good, '/ok', content_length_proc: ->(_length) { outer = CaseopsIosPods.current_open_uri_profile; n = $caseops_connects; refusal.call('IOS_PODS_NET_HTTP_STORE_REFUSED') { unknown.call }; check(CaseopsIosPods.current_open_uri_profile.equal?(outer) && $caseops_connects == n, 'TEST_HTTP_IDENTITY'); seen = true }); check(seen, 'TEST_IDENTITY_UNREACHED') },
    -> { value = read.call(good, '/ok', ssl_verify_mode: OpenSSL::SSL::VERIFY_PEER); check(value == 'ok', 'TEST_EXPLICIT_PEER') },
    -> { http = Net::HTTP.new('127.0.0.1', good.port, nil); http.use_ssl = true; http.cert = server_cert; http.key = server_key; http.open_timeout = http.read_timeout = http.write_timeout = 2; n = $caseops_connects; refusal.call('IOS_PODS_NET_HTTP_CLIENT_AUTH_REFUSED') { http.start { |client| client.get('/ok') } }; check($caseops_connects == n, 'TEST_CLIENT_AUTH_CONNECT') },
    -> { fault = RuntimeError.new('OWNED_SYNTHETIC_CALLBACK'); caught = nil; begin; read.call(good, '/ok', content_length_proc: ->(_length) { raise fault }); rescue RuntimeError => error; caught = error; end; check(caught.equal?(fault) && CaseopsIosPods.current_open_uri_profile.nil?, 'TEST_ORIGINAL_ERROR_IDENTITY') },
    -> { sentinel = Object.new; value = OpenURI.open_uri(url.call(good), open_timeout: 2, read_timeout: 2) { |io| body = io.read; check(body == 'ok', 'TEST_RETURN_BODY'); sentinel }; check(value.equal?(sentinel), 'TEST_ORIGINAL_RETURN_IDENTITY') },
  ]
  check(cases.length == CASE_IDS.length && CASE_IDS.uniq.length == CASE_IDS.length, 'TEST_COMPLETE_INVENTORY')
  emit = lambda do |id, phase, outcome, error = nil|
    row = { 'caseId' => id, 'phase' => phase, 'outcome' => outcome }
    if error
      row['errorClass'] = error.class.name
      message = error.message.to_s.split("\n", 2).first
      row['errorCode'] = message && message.match?(/\A(?:TEST|IOS_PODS)_[A-Z0-9_]+\z/) ? message : 'RUBY_TRANSPORT_CASE_FAILED'
    end
    reports << row; puts JSON.generate(row)
  end
  CASE_IDS.zip(cases).each do |id, body|
    reached = false
    begin
      check(Process.clock_gettime(Process::CLOCK_MONOTONIC) < deadline, 'TEST_DEADLINE'); check(CaseopsIosPods.current_open_uri_profile.nil?, 'TEST_SETUP_CONTEXT'); emit.call(id, 'setup', 'passed'); reached = true
      body.call; emit.call(id, 'call', 'passed')
    rescue StandardError => error
      failures += 1; emit.call(id, reached ? 'call' : 'setup', 'failed', error); emit.call(id, 'call', 'unreached') unless reached
    ensure
      begin
        check(CaseopsIosPods.current_open_uri_profile.nil?, 'TEST_TEARDOWN_CONTEXT'); check(servers.flat_map(&:rows).all? { |row| row['marker'] == 'no-paid-providers' }, 'TEST_RECEIVED_MARKER'); emit.call(id, 'teardown', 'passed')
      rescue StandardError => error
        failures += 1; emit.call(id, 'teardown', 'failed', error); Thread.current[CaseopsIosPods::OPEN_URI_PROFILE_KEY] = nil
      end
    end
  end
ensure
  servers.each(&:stop)
  CaseopsIosPods.finish!
  source.replace("\0" * source.bytesize); base.replace("\0" * base.bytesize); bundle.replace("\0" * bundle.bytesize)
end
check(reports.length == CASE_IDS.length * 3 && reports.map { |row| [row['caseId'], row['phase']] }.uniq.length == reports.length, 'TEST_ALL_PHASES')
puts JSON.generate({ 'summary' => true, 'cases' => CASE_IDS.length, 'phases' => reports.length, 'failedPhases' => reports.count { |row| row['outcome'] != 'passed' }, 'failures' => failures, 'receivedRequests' => servers.sum { |server| server.rows.length }, 'allReceivedMarkersExact' => servers.flat_map(&:rows).all? { |row| row['marker'] == 'no-paid-providers' }, 'allServerThreadsClosed' => true, 'SDKMutations' => 0, 'externalRequests' => 0, 'nativeAcceptance' => false })
exit(failures.zero? ? 0 : 1)
