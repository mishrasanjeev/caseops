import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.ByteBuffer;
import java.nio.channels.FileChannel;
import java.nio.file.*;
import java.security.*;
import java.security.cert.Certificate;
import java.security.cert.CertificateFactory;
import java.security.cert.X509Certificate;
import java.util.*;
import javax.net.ssl.*;

/** Public fixed-JDK cacerts only. This program never reads an owner keystore. */
public class HostPlatformTrust {
  static final String DENIED="86a1ecba089c4a8d3bbe2734c612ba341d813e043cf9e8a862cd5c57a36bbe6b";
  static final String ORIGINAL="dd829eff9efb6ceb6de8f403f34bb4758707952e55e0da800cc8f6be768771cc";
  static final String CLEAN="a5c7424bd0772d7a8f310ecd14d83293a188de3145f3a850a82483c6338441e2";
  static void need(boolean value,String code)throws Exception {if(!value)throw new Exception(code);}
  static String sha(byte[] value)throws Exception{return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(value));}
  static String quote(String value){return "\""+value.replace("\\","\\\\").replace("\"","\\\"").replace("\n","\\n").replace("\r","\\r")+"\"";}
  static TreeMap<String,String> entries(KeyStore store)throws Exception {
    TreeMap<String,String> result=new TreeMap<>();HashSet<String> fingerprints=new HashSet<>();
    for(String alias:Collections.list(store.aliases())){
      need(store.isCertificateEntry(alias)&&!store.isKeyEntry(alias),"PUBLIC_TRUSTED_CERTIFICATES_ONLY");
      String fingerprint=sha(store.getCertificate(alias).getEncoded());need(fingerprints.add(fingerprint),"DUPLICATE_CERTIFICATE_REFUSED");result.put(alias,fingerprint);
      need(result.size()<=256,"CERTIFICATE_COUNT_BOUND");
    }return result;
  }
  static String setHash(Collection<String> values)throws Exception {ArrayList<String> sorted=new ArrayList<>(values);Collections.sort(sorted);return sha((String.join("\n",sorted)+"\n").getBytes(StandardCharsets.US_ASCII));}
  static List<byte[]> publicFrames(int count)throws Exception {
    DataInputStream input=new DataInputStream(System.in);ArrayList<byte[]> result=new ArrayList<>();
    for(int i=0;i<count;i++){int size=input.readInt();need(size>0&&size<=1048576,"PUBLIC_INPUT_FRAME_BOUND");byte[] data=input.readNBytes(size);need(data.length==size,"PUBLIC_INPUT_FRAME_TRUNCATED");result.add(data);}
    need(input.read()==-1,"EXTRA_PUBLIC_INPUT_FRAME_REFUSED");return result;
  }
  static byte[] serialize(KeyStore store,String type,Map<String,String> expected)throws Exception {
    ByteArrayOutputStream memory=new ByteArrayOutputStream();store.store(memory,"changeit".toCharArray());byte[] retained=memory.toByteArray();
    need(retained.length>0&&retained.length<=1048576,"OUTPUT_STORE_BOUND");KeyStore check=KeyStore.getInstance(type);check.load(new ByteArrayInputStream(retained),"changeit".toCharArray());need(entries(check).equals(expected),"SERIALIZED_ALIASES_CHANGED");return retained;
  }
  static void writeFd(Path destination,byte[] retained)throws Exception {
    need(destination.toString().matches("/dev/fd/[0-9]{1,10}"),"ONLY_INHERITED_OUTPUT_DESCRIPTOR");long end=System.nanoTime()+5000000000L;
    // No CREATE/TRUNCATE or named output path: Python owns the already-open
    // exclusive O_RDWR descriptor and independently verifies it after return.
    try(FileChannel channel=FileChannel.open(destination,StandardOpenOption.READ,StandardOpenOption.WRITE)){
      need(channel.size()==0,"EMPTY_EXCLUSIVE_OUTPUT_REQUIRED");channel.position(0);ByteBuffer data=ByteBuffer.wrap(retained);
      while(data.hasRemaining()){need(System.nanoTime()<end,"OUTPUT_WRITE_DEADLINE");need(channel.write(data)>0,"OUTPUT_WRITE_NO_PROGRESS");}
      channel.force(true);need(channel.size()==retained.length,"OUTPUT_EXTENT_CHANGED");channel.position(0);ByteBuffer readback=ByteBuffer.allocate(retained.length+1);
      while(readback.hasRemaining()){need(System.nanoTime()<end,"OUTPUT_READBACK_DEADLINE");int n=channel.read(readback);if(n<0)break;need(n>0,"OUTPUT_READBACK_NO_PROGRESS");}
      need(readback.position()==retained.length&&Arrays.equals(Arrays.copyOf(readback.array(),readback.position()),retained),"OUTPUT_RETAINED_BYTES_CHANGED");
    }
  }
  static void checkSet(Collection<String> values)throws Exception {
    String hash=setHash(values);need(values.size()==118&&hash.equals(ORIGINAL)||values.size()==117&&hash.equals(CLEAN),"UNKNOWN_TRUST_SET_REFUSED");
    need(Collections.frequency(new ArrayList<>(values),DENIED)==(hash.equals(ORIGINAL)?1:0),"DENIED_ROOT_STATE_REFUSED");
  }
  static TreeSet<String> defaults()throws Exception {
    TrustManagerFactory factory=TrustManagerFactory.getInstance(TrustManagerFactory.getDefaultAlgorithm());need(factory.getAlgorithm().equals("PKIX"),"PINNED_PKIX_REQUIRED");factory.init((KeyStore)null);
    TreeSet<String> result=new TreeSet<>();for(var manager:factory.getTrustManagers())if(manager instanceof X509TrustManager x)for(var cert:x.getAcceptedIssuers())need(result.add(sha(cert.getEncoded())),"DUPLICATE_DEFAULT_ROOT");return result;
  }
  static void inspect()throws Exception {
    TreeSet<String> values=defaults();checkSet(values);System.out.println("{\"count\":"+values.size()+",\"setSha256\":"+quote(setHash(values))+",\"deniedCount\":"+(values.contains(DENIED)?1:0)+"}");
  }
  static void fixture(Path destination)throws Exception {
    String version=System.getProperty("java.version"),type=version.equals("21.0.12.1")?"PKCS12":version.equals("17.0.20.1")?"JKS":"";
    need(!type.isEmpty(),"PINNED_JDK_REQUIRED");List<byte[]> frames=publicFrames(2);KeyStore store=KeyStore.getInstance(type);store.load(new ByteArrayInputStream(frames.get(0)),"changeit".toCharArray());
    TreeMap<String,String> before=entries(store);need(before.size()==117&&setHash(before.values()).equals(CLEAN),"EXACT_QA_BASE_STORE_REQUIRED");
    X509Certificate ca;try(InputStream stream=new ByteArrayInputStream(frames.get(1))){ca=(X509Certificate)CertificateFactory.getInstance("X.509").generateCertificate(stream);byte[] remainder=stream.readNBytes(1025);need(remainder.length<=1024,"ONE_FIXTURE_CERTIFICATE_REQUIRED");for(byte value:remainder)need(value==10||value==13||value==32||value==9,"ONE_FIXTURE_CERTIFICATE_REQUIRED");}
    ca.checkValidity();need(ca.getBasicConstraints()>=0,"FIXTURE_CA_REQUIRED");String fingerprint=sha(ca.getEncoded());need(!fingerprint.equals(DENIED)&&!before.containsValue(fingerprint),"FIXTURE_ROOT_IDENTITY_REFUSED");
    String alias="caseops-owned-loopback-fixture-"+fingerprint;store.setCertificateEntry(alias,ca);TreeMap<String,String> after=entries(store),expected=new TreeMap<>(before);expected.put(alias,fingerprint);need(after.equals(expected),"QA_BASE_ALIASES_CHANGED");
    byte[] retained=serialize(store,type,after);writeFd(destination,retained);
    StringJoiner aliases=new StringJoiner(",","{","}");for(var entry:after.entrySet())aliases.add(quote(entry.getKey())+":"+quote(entry.getValue()));
    System.out.println("{\"outputCount\":118,\"fixtureSha256\":"+quote(fingerprint)+",\"outputSetSha256\":"+quote(setHash(after.values()))+",\"baseAliasesPreserved\":true,\"outputSizeBytes\":"+retained.length+",\"outputSha256\":"+quote(sha(retained))+",\"aliases\":"+aliases+"}");
  }
  static void prepare(Path destination)throws Exception {
    String version=System.getProperty("java.version");String type=version.equals("21.0.12.1")?"PKCS12":version.equals("17.0.20.1")?"JKS":"";
    need(!type.isEmpty()&&System.getProperty("java.runtime.version").startsWith(version+"+1"),"PINNED_JDK_REQUIRED");
    need(System.getProperty("javax.net.ssl.trustStore")==null,"INHERITED_TRUSTSTORE_REFUSED");
    Path home=Path.of(System.getProperty("java.home")).toRealPath();Path source=home.resolve("lib/security/cacerts");
    need(!Files.exists(home.resolve("lib/security/jssecacerts"))&&Files.isRegularFile(source,LinkOption.NOFOLLOW_LINKS)&&Files.size(source)<=1048576,"FIXED_PUBLIC_CACERTS_REQUIRED");
    KeyStore store=KeyStore.getInstance(type);store.load(new ByteArrayInputStream(publicFrames(1).get(0)),"changeit".toCharArray());need(store.getType().equalsIgnoreCase(type),"PINNED_STORE_TYPE_REQUIRED");
    TreeMap<String,String> before=entries(store);checkSet(before.values());need(defaults().equals(new TreeSet<>(before.values())),"ACTUAL_DEFAULT_STORE_MISMATCH");
    for(var entry:before.entrySet())if(entry.getValue().equals(DENIED))store.deleteEntry(entry.getKey());
    TreeMap<String,String> after=entries(store),expected=new TreeMap<>(before);expected.entrySet().removeIf(entry->entry.getValue().equals(DENIED));
    need(after.equals(expected)&&after.size()==117&&setHash(after.values()).equals(CLEAN),"OTHER_ALIASES_NOT_PRESERVED");
    byte[] retained=serialize(store,type,after);writeFd(destination,retained);
    StringJoiner aliases=new StringJoiner(",","{","}");for(var entry:after.entrySet())aliases.add(quote(entry.getKey())+":"+quote(entry.getValue()));
    System.out.println("{\"inputCount\":"+before.size()+",\"outputCount\":117,\"outputSetSha256\":"+quote(CLEAN)+",\"aliasesPreserved\":true,\"storeType\":"+quote(type)+",\"outputSizeBytes\":"+retained.length+",\"outputSha256\":"+quote(sha(retained))+",\"aliases\":"+aliases+"}");
  }
  static String sharedSet(Collection<String> values,String fixture)throws Exception {
    need(fixture.equals("-")||fixture.matches("[a-f0-9]{64}"),"EXACT_SHARED_FIXTURE_TOKEN");
    ArrayList<String> clean=new ArrayList<>(values);need(new HashSet<>(clean).size()==clean.size()&&!clean.contains(DENIED),"SHARED_DUPLICATE_OR_DENIED_ROOT");
    if(!fixture.equals("-")){need(Collections.frequency(clean,fixture)==1,"EXACT_SHARED_QA_ANCHOR");clean.remove(fixture);}
    need(clean.size()==117&&setHash(clean).equals(CLEAN)&&values.size()==(fixture.equals("-")?117:118),"SHARED_OTHER_ANCHORS_CHANGED");return setHash(values);
  }
  static void sharedRuntime()throws Exception {
    String version=System.getProperty("java.version");need(Set.of("21.0.12.1","17.0.20.1").contains(version)&&System.getProperty("java.runtime.version").startsWith(version+"+1"),"PINNED_SHARED_JDK_REQUIRED");
  }
  static void decodeShared(String fixture)throws Exception {
    sharedRuntime();byte[] retained=publicFrames(1).get(0);KeyStore store=KeyStore.getInstance("PKCS12");store.load(new ByteArrayInputStream(retained),"changeit".toCharArray());TreeMap<String,String> aliases=entries(store);String hash=sharedSet(aliases.values(),fixture);StringJoiner encoded=new StringJoiner(",","{","}");for(var entry:aliases.entrySet())encoded.add(quote(entry.getKey())+":"+quote(entry.getValue()));
    System.out.println("{\"storeType\":\"PKCS12\",\"inputSha256\":"+quote(sha(retained))+",\"inputSizeBytes\":"+retained.length+",\"aliases\":"+encoded+",\"count\":"+aliases.size()+",\"setSha256\":"+quote(hash)+"}");
  }
  static void inspectShared(String fixture)throws Exception {
    sharedRuntime();TreeSet<String> roots=defaults();String hash=sharedSet(roots,fixture);System.out.println("{\"count\":"+roots.size()+",\"setSha256\":"+quote(hash)+",\"deniedCount\":0}");
  }
  static void probe(String raw)throws Exception {
    URI uri=new URI(raw);need(uri.getScheme().equals("https")&&Set.of("localhost","127.0.0.1").contains(uri.getHost())&&uri.getPort()>1023&&uri.getRawUserInfo()==null&&uri.getRawQuery()==null&&uri.getRawFragment()==null&&uri.getPath().equals("/trust-probe"),"LOOPBACK_METADATA_PROBE_ONLY");
    URL target=new URI("https",null,uri.getHost().equals("localhost")?"localhost":"127.0.0.1",uri.getPort(),"/trust-probe",null,null).toURL();
    HttpsURLConnection connection=(HttpsURLConnection)target.openConnection();connection.setConnectTimeout(3000);connection.setReadTimeout(3000);connection.setInstanceFollowRedirects(false);connection.setRequestProperty("X-CaseOps-Automated-Test","no-paid-providers");
    try {need(connection.getResponseCode()==200,"LOCAL_PROBE_STATUS");try(InputStream input=connection.getInputStream()){byte[] body=input.readNBytes(65537);need(body.length<=65536&&new String(body,StandardCharsets.UTF_8).equals("public-trust-ok"),"LOCAL_PROBE_BODY");}System.out.println("{\"connected\":true}");}finally{connection.disconnect();}
  }
  public static void main(String[] args)throws Exception {
    try {need(args.length>0,"EXACT_ACTION_REQUIRED");switch(args[0]){case "prepare":need(args.length==2,"ONE_OUTPUT_REQUIRED");prepare(Path.of(args[1]));break;case "inspect":need(args.length==1,"NO_INSPECT_ARGUMENTS");inspect();break;case "fixture":need(args.length==2,"EXACT_FIXTURE_ARGUMENTS");fixture(Path.of(args[1]));break;case "decode-shared":need(args.length==2,"ONE_SHARED_FIXTURE_TOKEN");decodeShared(args[1]);break;case "inspect-shared":need(args.length==2,"ONE_SHARED_FIXTURE_TOKEN");inspectShared(args[1]);break;case "probe":need(args.length==2,"ONE_LOCAL_PROBE");probe(args[1]);break;default:throw new Exception("UNKNOWN_ACTION");}}
    catch(Exception error){System.err.println("Host platform trust refused: "+error.getClass().getSimpleName());System.exit(37);}
  }
}
