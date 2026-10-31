# Host-only CocoaPods constructor policy. No installation or network on load.
require 'json'
require 'digest'
require 'openssl'
require 'uri'

module CaseopsIosPods
  MARKER = 'no-paid-providers'.freeze
  ROOT_SET = '105453e7eeeb26f9778e22b4212b7a6725079827b4de684784eacde93845787a'.freeze
  FIELDS = [:dev, :ino, :mode, :uid, :gid, :nlink, :size].freeze
  def self.need(value, code)
    raise code unless value
  end
  def self.frame(stat)
    FIELDS.map { |key| stat.public_send(key) } + [(stat.mtime.to_r * 1_000_000_000).to_i, (stat.ctime.to_r * 1_000_000_000).to_i]
  end
  def self.namespace(file)
    rows = []
    parent = File.dirname(file)
    loop do
      need(rows.length < 128, 'IOS_PODS_NAMESPACE_BOUND')
      value = File.lstat(parent)
      need(value.directory? && !value.symlink?, 'IOS_PODS_NAMESPACE')
      rows << [parent, value.dev, value.ino, value.mode, value.uid, value.gid]
      break if File.dirname(parent) == parent
      parent = File.dirname(parent)
    end
    rows
  end
  def self.no_profiles!
    home = @policy.fetch('home')
    value = File.lstat(home)
    need(value.directory? && !value.symlink? && value.uid == Process.uid && (value.mode & 0o077).zero? && File.realpath(home) == home, 'IOS_PODS_HOME')
    %w[.netrc _netrc .curlrc .npmrc .gemrc .bundle .cocoapods].each do |name|
      need(!File.exist?(File.join(home, name)) && !File.symlink?(File.join(home, name)), 'IOS_PODS_OWNER_CONFIG_REFUSED')
    end
    [frame(value), namespace(home)]
  end
  def self.check_bundle!
    ref = @policy.fetch('bundle')
    need(File.realpath(ref.fetch('path')) == ref.fetch('path'), 'IOS_PODS_CA_NAMESPACE')
    need(frame(File.lstat(ref.fetch('path'))) == @bundle_frame && namespace(ref.fetch('path')) == @bundle_namespace, 'IOS_PODS_CA_CHANGED')
  end
  def self.admit!
    raw = ENV.fetch('CASEOPS_IOS_PODS_TLS_POLICY')
    need(raw.bytesize <= 8192, 'IOS_PODS_POLICY_BOUND')
    @policy = JSON.parse(raw)
    need(@policy.keys.sort == %w[bundle empty fixtureSha256 home podHome rubyGems].sort, 'IOS_PODS_POLICY_KEYS')
    need(ENV['HOME'] == @policy.fetch('home') && ENV['CURL_HOME'] == ENV['HOME'] && ENV['GEM_HOME'] == @policy.fetch('podHome') && ENV['GEM_PATH'] == [ENV['GEM_HOME'], @policy.fetch('rubyGems')].join(':'), 'IOS_PODS_SCOPED_HOME')
    need(ENV['SSL_CERT_FILE'] == @policy.fetch('bundle').fetch('path') && ENV['SSL_CERT_DIR'] == @policy.fetch('empty'), 'IOS_PODS_SCOPED_CA')
    need(%w[NODE_OPTIONS NODE_EXTRA_CA_CERTS NODE_USE_SYSTEM_CA RUBYOPT RUBYLIB OPENSSL_CONF OPENSSL_CONF_INCLUDE HTTP_PROXY HTTPS_PROXY ALL_PROXY http_proxy https_proxy all_proxy CURL_CA_BUNDLE].all? { |key| !ENV.key?(key) }, 'IOS_PODS_OVERRIDE_REFUSED')
    @home_frame = no_profiles!
    empty = File.lstat(@policy.fetch('empty'))
    need(empty.directory? && !empty.symlink? && empty.uid == Process.uid && (empty.mode & 0o077).zero?, 'IOS_PODS_EMPTY_DIRECTORY')
    Dir.open(@policy.fetch('empty')) do |dir|
      # read only the two mandatory dot entries and one EOF/overflow probe.
      need(dir.read == '.' && dir.read == '..' && dir.read.nil?, 'IOS_PODS_EMPTY_DIRECTORY')
    end
    ref = @policy.fetch('bundle')
    need(ref.keys.sort == %w[path sha256 sizeBytes].sort && ref.fetch('sha256').match?(/\A[a-f0-9]{64}\z/) && ref.fetch('sizeBytes').is_a?(Integer) && ref.fetch('sizeBytes').between?(1, 1_048_576), 'IOS_PODS_CA_REFERENCE')
    flags = File::RDONLY | File::NOFOLLOW | File::NONBLOCK
    File.open(ref.fetch('path'), flags) do |file|
      before = file.stat
      need(before.file? && before.uid == Process.uid && before.nlink == 1 && (before.mode & 0o7777) == 0o600 && before.size == ref.fetch('sizeBytes') && frame(before) == frame(File.lstat(ref.fetch('path'))), 'IOS_PODS_CA_IDENTITY')
      @bundle_namespace = namespace(ref.fetch('path')); @bundle_frame = frame(before)
      bytes = file.read(before.size + 1)
      need(bytes.bytesize == before.size && Digest::SHA256.hexdigest(bytes) == ref.fetch('sha256') && frame(file.stat) == @bundle_frame, 'IOS_PODS_CA_CHANGED')
      rows = bytes.scan(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/)
      need(bytes.gsub(/-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----/, '').strip.empty?, 'IOS_PODS_CA_PEM')
      ids = rows.map { |pem| Digest::SHA256.hexdigest(OpenSSL::X509::Certificate.new(pem).to_der) }
      need(ids.uniq.length == ids.length, 'IOS_PODS_DUPLICATE_CA')
      base = ids.reject { |id| id == @policy['fixtureSha256'] }
      need(base.length == 188 && Digest::SHA256.hexdigest(base.sort.join("\n") + "\n") == ROOT_SET && ids.length == 188 + (@policy['fixtureSha256'].nil? ? 0 : 1), 'IOS_PODS_RUBY188_SET')
      @retained_ca = bytes
      @cert_store = OpenSSL::X509::Store.new
      rows.each { |pem| @cert_store.add_cert(OpenSSL::X509::Certificate.new(pem)) }
      check_bundle!
    end
    require 'rubygems'
    Gem.use_paths(@policy.fetch('podHome'), [@policy.fetch('podHome'), @policy.fetch('rubyGems')])
    {'typhoeus' => '1.6.0', 'ethon' => '0.18.0', 'cocoapods-core' => '1.17.0', 'cocoapods-downloader' => '2.1', 'cocoapods' => '1.17.0'}.each do |name, version|
      spec = Gem::Specification.find_by_name(name, version)
      need(File.realpath(spec.full_gem_path).start_with?(@policy.fetch('podHome') + '/gems/'), 'IOS_PODS_GEM_ORIGIN')
    end
    require 'typhoeus'
    require 'cocoapods'
    require 'net/http'
    require 'open-uri'
    admit_open_uri!
    Typhoeus::Request.prepend(Constructor) unless Typhoeus::Request.ancestors.include?(Constructor)
    Pod::Executable.singleton_class.prepend(ExecutableResolver) unless Pod::Executable.singleton_class.ancestors.include?(ExecutableResolver)
    Net::HTTP.prepend(NetHttpConstructor) unless Net::HTTP.ancestors.include?(NetHttpConstructor)
    Net::HTTP.singleton_class.prepend(NetHttpClass) unless Net::HTTP.singleton_class.ancestors.include?(NetHttpClass)
    self
  end
  OPEN_URI_SOURCE_SHA256 = '87056fcf0483dad72a3388cccfbd7b1fda4aa78545dfcb99ef13383c5a8eff02'.freeze
  OPEN_URI_PROFILE_KEY = :caseops_ios_open_uri_default_store_profile
  OpenUriProfile = Struct.new(:host, :port, :http, :store, :pinned, :fiber, :active, keyword_init: true)
  def self.admit_open_uri!
    abi = File.basename(@policy.fetch('rubyGems'))
    need(abi.match?(/\A[0-9]+\.[0-9]+\.[0-9]+\z/), 'IOS_PODS_OPEN_URI_SOURCE')
    file = File.expand_path('../../' + abi + '/open-uri.rb', @policy.fetch('rubyGems'))
    need(File.realpath(file) == file, 'IOS_PODS_OPEN_URI_SOURCE')
    File.open(file, File::RDONLY | File::NOFOLLOW | File::NONBLOCK) do |input|
      before = input.stat
      need(before.file? && before.uid == Process.uid && before.nlink == 1 && (before.mode & 0o022).zero? && before.size.between?(1, 65_536) && frame(before) == frame(File.lstat(file)), 'IOS_PODS_OPEN_URI_SOURCE')
      parents = namespace(file); bytes = input.read(before.size + 1)
      need(bytes.bytesize == before.size && Digest::SHA256.hexdigest(bytes) == OPEN_URI_SOURCE_SHA256 && frame(input.stat) == frame(before) && frame(File.lstat(file)) == frame(before) && namespace(file) == parents, 'IOS_PODS_OPEN_URI_SOURCE')
      @open_uri_file = file; @open_uri_frame = frame(before); @open_uri_namespace = parents
    ensure
      bytes&.replace("\0" * bytes.bytesize)
    end
    original = OpenURI.method(:open_http)
    original = original.super_method if original.owner == OpenUriConstructor
    need(original && original.owner == OpenURI.singleton_class && original.source_location == [file, 283], 'IOS_PODS_OPEN_URI_SOURCE')
    @open_uri_original = original
    OpenURI.singleton_class.prepend(OpenUriConstructor) unless OpenURI.singleton_class.ancestors.include?(OpenUriConstructor)
  end
  def self.current_open_uri_profile
    Thread.current[OPEN_URI_PROFILE_KEY] # Ruby Thread#[] is fiber-local.
  end
  def self.open_uri(buf, target, proxy, options)
    previous = current_open_uri_profile; profile = nil
    no_profiles!; check_bundle!
    need(frame(File.lstat(@open_uri_file)) == @open_uri_frame && namespace(@open_uri_file) == @open_uri_namespace && File.realpath(@open_uri_file) == @open_uri_file, 'IOS_PODS_OPEN_URI_SOURCE')
    need(target.instance_of?(URI::HTTPS) && target.userinfo.nil? && target.fragment.nil? && proxy.nil? && options.instance_of?(Hash), 'IOS_PODS_OPEN_URI_HTTPS_REQUIRED')
    need(options[:ssl_ca_cert].nil? && options[:ssl_min_version].nil? && options[:ssl_max_version].nil?, 'IOS_PODS_OPEN_URI_DEFAULT_CA_REQUIRED')
    need(options[:ssl_verify_mode].nil? || options[:ssl_verify_mode] == OpenSSL::SSL::VERIFY_PEER, 'IOS_PODS_NET_HTTP_VERIFY_REQUIRED')
    profile = OpenUriProfile.new(host: target.hostname.dup.freeze, port: target.port, pinned: @cert_store, fiber: Fiber.current, active: true)
    Thread.current[OPEN_URI_PROFILE_KEY] = profile
    @open_uri_original.call(buf, target, proxy, options)
  ensure
    if profile
      profile.active = false
      Thread.current[OPEN_URI_PROFILE_KEY] = previous
    end
  end
  def self.capture_open_uri_store(http, store, location)
    return if store.nil? || store.equal?(@cert_store)
    profile = current_open_uri_profile
    return unless profile
    need(profile.active && profile.fiber.equal?(Fiber.current) && profile.pinned.equal?(@cert_store) && profile.http.nil? && profile.store.nil? && http.instance_of?(Net::HTTP) && http.address == profile.host && http.port == profile.port && store.instance_of?(OpenSSL::X509::Store) && location && location.absolute_path == @open_uri_file && location.lineno == 343, 'IOS_PODS_NET_HTTP_STORE_REFUSED')
    profile.http = http; profile.store = store
  end
  def self.open_uri_store?(http, store)
    profile = current_open_uri_profile
    profile && profile.active && profile.fiber.equal?(Fiber.current) && profile.pinned.equal?(@cert_store) && profile.http.equal?(http) && profile.store.equal?(store)
  end
  module OpenUriConstructor
    def open_http(buf, target, proxy, options)
      CaseopsIosPods.open_uri(buf, target, proxy, options)
    end
  end
  def self.options(url, options)
    no_profiles!; check_bundle!
    uri = URI.parse(url)
    need(uri.is_a?(URI::HTTPS) && uri.userinfo.nil? && uri.fragment.nil? && !url.include?('#'), 'IOS_PODS_HTTPS_REQUIRED')
    need(options.is_a?(Hash), 'IOS_PODS_TYPED_OPTIONS')
    expected = { :cainfo => @policy.fetch('bundle').fetch('path'), :capath => @policy.fetch('empty'), :ssl_verifypeer => true, :ssl_verifyhost => 2 }
    options.each do |key, value|
      name = key.to_s
      need(!name.match?(/proxy|ssl_ctx|sslcert|sslkey|pinnedpublickey|ca_info_blob|certinfo|issuercert/i), 'IOS_PODS_TRUST_OPTION_REFUSED')
      need(!name.match?(/\A(?:ca|ssl_)/) || expected.key?(key) && expected[key] == value, 'IOS_PODS_TRUST_OPTION_REFUSED')
    end
    if options.key?(:netrc_file)
      need(options[:netrc] == :optional && options[:netrc_file] == File.join(@policy.fetch('home'), '.netrc'), 'IOS_PODS_NETRC_REFUSED')
    end
    headers = options.fetch(:headers, {})
    need(headers.is_a?(Hash) && headers.length <= 32, 'IOS_PODS_HEADERS')
    headers.each do |key, value|
      need(key.is_a?(String) && value.is_a?(String) && key.bytesize <= 128 && value.bytesize <= 4096 && ![key, value].any? { |v| v.match?(/[\r\n\x00]/) }, 'IOS_PODS_HEADERS')
      need(key.downcase != 'x-caseops-automated-test' || key == 'X-CaseOps-Automated-Test' && value == MARKER, 'IOS_PODS_MARKER')
    end
    options.merge(expected).merge(:headers => headers.merge('X-CaseOps-Automated-Test' => MARKER))
  end
  module Constructor
    def initialize(url, options = {})
      super(url, CaseopsIosPods.options(url, options))
    end
  end
  module NetHttpConstructor
    def cert_store=(value)
      CaseopsIosPods.capture_open_uri_store(self, value, caller_locations(1, 1).first)
      super(value)
    end
    def start(*args, &block)
      CaseopsIosPods.no_profiles!; CaseopsIosPods.check_bundle!
      CaseopsIosPods.need(use_ssl? && !proxy?, 'IOS_PODS_NET_HTTP_HTTPS_REQUIRED')
      policy = CaseopsIosPods.instance_variable_get(:@policy)
      store = CaseopsIosPods.instance_variable_get(:@cert_store)
      CaseopsIosPods.need(cert_store.nil? || cert_store.equal?(store) || CaseopsIosPods.open_uri_store?(self, cert_store), 'IOS_PODS_NET_HTTP_STORE_REFUSED')
      CaseopsIosPods.need(verify_mode.nil? || verify_mode == OpenSSL::SSL::VERIFY_PEER, 'IOS_PODS_NET_HTTP_VERIFY_REQUIRED')
      CaseopsIosPods.need(verify_hostname.nil? || verify_hostname == true, 'IOS_PODS_NET_HTTP_HOST_REQUIRED')
      CaseopsIosPods.need(ca_file.nil? || ca_file == policy.fetch('bundle').fetch('path'), 'IOS_PODS_NET_HTTP_STORE_REFUSED')
      CaseopsIosPods.need(ca_path.nil? || ca_path == policy.fetch('empty'), 'IOS_PODS_NET_HTTP_STORE_REFUSED')
      CaseopsIosPods.need(cert.nil? && key.nil? && extra_chain_cert.nil?, 'IOS_PODS_NET_HTTP_CLIENT_AUTH_REFUSED')
      self.cert_store = store; self.ca_file = nil; self.ca_path = nil
      self.verify_mode = OpenSSL::SSL::VERIFY_PEER; self.verify_hostname = true
      # Preserve Net::HTTP's existing finite defaults or a stricter caller value.
      [open_timeout, read_timeout, write_timeout].each do |value|
        CaseopsIosPods.need(value.is_a?(Numeric) && value.positive? && value <= 60, 'IOS_PODS_NET_HTTP_TIMEOUT')
      end
      super(*args, &block)
    end
    def request(req, body = nil, &block)
      CaseopsIosPods.no_profiles!; CaseopsIosPods.check_bundle!
      CaseopsIosPods.need(use_ssl? && !proxy? && req.is_a?(Net::HTTP::Get) && body.nil? && req.body.nil?, 'IOS_PODS_NET_HTTP_GET_REQUIRED')
      marker = req['X-CaseOps-Automated-Test']
      CaseopsIosPods.need(marker.nil? || marker == CaseopsIosPods::MARKER, 'IOS_PODS_MARKER')
      req['X-CaseOps-Automated-Test'] = CaseopsIosPods::MARKER
      super(req, body, &block)
    end
  end
  module NetHttpClass
    def get_response(uri, *args, &block)
      CaseopsIosPods.need(args.empty? && uri.is_a?(URI::HTTPS) && uri.userinfo.nil? && uri.fragment.nil?, 'IOS_PODS_NET_HTTP_URI_REQUIRED')
      super(uri, &block)
    end
  end
  module ExecutableResolver
    def which(program)
      name = program.to_s
      # CocoaPods normally prepends './' ahead of PATH. These exact reviewed
      # constructors must use the owned shim even if cwd contains a namesake.
      if %w[curl node npm ruby pod git].include?(name)
        file = File.join(File.dirname(CaseopsIosPods.instance_variable_get(:@policy).fetch('bundle').fetch('path')), 'bin', name)
        value = File.lstat(file)
        CaseopsIosPods.need(value.file? && !value.symlink? && value.uid == Process.uid && value.nlink == 1 && (value.mode & 0o7777) == 0o700 && File.realpath(file) == file, 'IOS_PODS_SHIM_IDENTITY')
        file
      else
        super
      end
    end
  end
  def self.finish!
    check_bundle!
    need(no_profiles! == @home_frame, 'IOS_PODS_HOME_CHANGED')
  ensure
    @retained_ca&.replace("\0" * @retained_ca.bytesize)
  end
  def self.run
    admit!
    # Strict core unpack avoids an undeclared optional base64 gem.
    source = ENV.fetch('CASEOPS_IOS_POD_SOURCE_BASE64').unpack1('m0')
    need(source.bytesize.between?(1, 32_768), 'IOS_PODS_ENTRY_BOUND')
    filename = File.join(@policy.fetch('podHome'), 'bin/pod')
    begin
      eval(source, TOPLEVEL_BINDING, filename)
    ensure
      original = $!
      begin
        finish!
      rescue StandardError
        warn('IOS_PODS_POSTFLIGHT_REFUSED')
        raise unless original
      ensure
        source.replace("\0" * source.bytesize)
      end
    end
  end
end
