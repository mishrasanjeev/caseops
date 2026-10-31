/* Local AAB verification, JDK source-file mode. No signing/key/network calls. */
import java.io.InputStream;
import java.security.CodeSigner;
import java.security.MessageDigest;
import java.security.cert.X509Certificate;
import java.util.Base64;
import java.util.HexFormat;
import java.util.HashSet;
import java.util.jar.JarFile;
import java.util.zip.ZipEntry;

public final class StoreJarVerifier {
    public static void main(String[] args) {
        try {
            if (args.length != 2 || !args[1].matches("[a-f0-9]{64}")) throw new Exception();
            long total = 0; int count = 0, signed = 0; byte[] certificate = null;
            HashSet<String> names = new HashSet<>();
            try (JarFile jar = new JarFile(args[0], true)) {
                var entries = jar.entries();
                byte[] buffer = new byte[65536];
                while (entries.hasMoreElements()) {
                    ZipEntry entry = entries.nextElement();
                    if (++count > 30000 || !names.add(entry.getName()) || entry.getSize() < 0
                            || entry.getSize() > 134217728) throw new Exception();
                    long bytes = 0;
                    try (InputStream input = jar.getInputStream(entry)) {
                        int n;
                        while ((n = input.read(buffer)) != -1) {
                            bytes += n; total += n;
                            if (bytes > 134217728 || total > 1073741824) throw new Exception();
                        }
                    }
                    if (bytes != entry.getSize()) throw new Exception();
                    if (entry.isDirectory() || entry.getName().matches("META-INF/(MANIFEST\\.MF|[A-Za-z0-9_-]+\\.(SF|RSA|DSA|EC))")) continue;
                    CodeSigner[] signers = ((java.util.jar.JarEntry) entry).getCodeSigners();
                    if (signers == null || signers.length != 1) throw new Exception();
                    X509Certificate leaf = (X509Certificate) signers[0].getSignerCertPath().getCertificates().get(0);
                    leaf.checkValidity();
                    byte[] encoded = leaf.getEncoded();
                    String digest = HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256").digest(encoded));
                    if (!digest.equals(args[1]) || (certificate != null && !MessageDigest.isEqual(certificate, encoded))) throw new Exception();
                    certificate = encoded; signed++;
                }
            }
            if (signed == 0 || certificate == null) throw new Exception();
            System.out.println("{\"signerCount\":1,\"signedEntries\":" + signed
                    + ",\"entryCount\":" + count + ",\"readBytes\":" + total
                    + ",\"certificateBase64\":\"" + Base64.getEncoder().encodeToString(certificate) + "\"}");
        } catch (Exception failure) {
            System.err.println("STORE_JAR_VERIFICATION_REFUSED");
            System.exit(37);
        }
    }
}
