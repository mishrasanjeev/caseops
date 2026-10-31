package ai.caseops.mobile.qa;

import android.app.Application;
import android.app.Service;
import android.content.Intent;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Binder;
import android.os.IBinder;
import android.os.Parcel;
import android.os.Process;
import android.os.SystemClock;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONObject;
import java.io.File;
import java.io.FileDescriptor;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Set;

/** Signature-permission bound service. All private reads run at this actual QA UID. */
public final class QaPrivacyService extends Service {
 static final String SIDECAR="ai.caseops.qa.privacyobserver", DESCRIPTOR="ai.caseops.qa.private-observer.v1", WITNESS="ai.caseops.qa.lifecycle.v1";
 static final Object LIFE=new Object();static long events,lastMainCreatedElapsed=-1;static int witnessPid=-1,pendingWitnessPid=-1;static IBinder witness,pendingWitness;
 static void witnessDied(IBinder token){synchronized(LIFE){
  boolean changed=false;
  if(witness==token){witness=null;witnessPid=-1;changed=true;}
  if(pendingWitness==token){pendingWitness=null;pendingWitnessPid=-1;changed=true;}
  if(changed)events++;
 }}
 static void witnessReady(IBinder token,int pid){
  QaPrivacyReader.need(pid==pendingWitnessPid&&token==pendingWitness,"QA_OBSERVER_WITNESS_READY_IDENTITY");
  witnessPid=pendingWitnessPid;witness=pendingWitness;
 }
 static long sequence(){synchronized(LIFE){return events;}}
 static long lastMainCreated(){synchronized(LIFE){return lastMainCreatedElapsed;}}
 static void requireWitness(JSONObject main,QaPrivacyReader.Guard guard)throws Exception{
  if(!main.getBoolean("present"))return;int pid=main.getInt("pid");long readyEnd=Math.min(guard.deadline,SystemClock.elapsedRealtime()+500);IBinder token=null;
  while(token==null){guard.check();synchronized(LIFE){if(witnessPid==pid)token=witness;}if(token==null){QaPrivacyReader.need(SystemClock.elapsedRealtime()<readyEnd,"QA_OBSERVER_MAIN_WITNESS_UNAVAILABLE");Thread.sleep(5);}}
  Parcel request=Parcel.obtain(),reply=Parcel.obtain();try{request.writeInterfaceToken(WITNESS);request.writeInt((int)Math.min(1000,Math.max(1,guard.deadline-SystemClock.elapsedRealtime())));QaPrivacyReader.need(token.transact(1,request,reply,0),"QA_OBSERVER_WITNESS_TRANSPORT");reply.readException();QaPrivacyReader.need(reply.readInt()==1,"QA_OBSERVER_WITNESS_NOT_DRAINED");}finally{request.recycle();reply.recycle();}
 }
 static final Set<String> REQUEST_KEYS=new HashSet<>(Arrays.asList("schemaVersion","requestId","operation","sourceSha","targetApkSha256","observerApkSha256","signerSha256","milliseconds","domain","allowQaFixtureUnstop","sidecarStartElapsed","mainExpected"));
 private final Object leaseLock=new Object();private Lease active;private final android.os.Handler expiry=new android.os.Handler(android.os.Looper.getMainLooper());
 private static final class Lease {String id;int uid,pid;boolean linked;IBinder token;IBinder.DeathRecipient death;Runnable timeout;QaPrivacyReader.Guard guard;QaPrivacyReader.Result result;void wipe(){guard.cancelled.set(true);if(result!=null)result.wipe();}}
 private void closeLease(Lease lease){
  lease.wipe();try{if(lease.timeout!=null)expiry.removeCallbacks(lease.timeout);if(lease.linked){try{lease.token.unlinkToDeath(lease.death,0);}catch(java.util.NoSuchElementException dead){QaPrivacyReader.need(!lease.token.isBinderAlive(),"QA_OBSERVER_DEATH_LINK_CLEANUP");}}}finally{if(active==lease)active=null;}
 }
 @Override public void onCreate(){super.onCreate();QaPrivacyReader.need(QaPrivacyReader.APP.equals(getPackageName())&&QaPrivacyReader.OBSERVER.equals(Application.getProcessName())&&getApplicationContext().getClass()==Application.class,"QA_OBSERVER_PROCESS_CONSTRUCTION");QaPrivacyReader.need((getApplicationInfo().flags&ApplicationInfo.FLAG_DEBUGGABLE)==0,"QA_OBSERVER_NONDEBUGGABLE");}
 @Override public IBinder onBind(Intent intent){return endpoint;}
 private static String digest(byte[] raw)throws Exception{byte[] d=MessageDigest.getInstance("SHA-256").digest(raw);StringBuilder s=new StringBuilder();for(byte b:d)s.append(String.format(java.util.Locale.ROOT,"%02x",b&255));return s.toString();}
 private String signer(String name,QaPrivacyReader.Guard g)throws Exception{PackageInfo info=getPackageManager().getPackageInfo(name,PackageManager.GET_SIGNING_CERTIFICATES);QaPrivacyReader.need(info.signingInfo!=null&&!info.signingInfo.hasMultipleSigners()&&info.signingInfo.getApkContentsSigners().length==1,"QA_OBSERVER_SINGLE_SIGNER");byte[] certificate=info.signingInfo.getApkContentsSigners()[0].toByteArray();try{g.bytes(certificate.length,true);QaPrivacyReader.need(certificate.length>0&&certificate.length<=16384,"QA_OBSERVER_CERTIFICATE_BOUND");return digest(certificate);}finally{Arrays.fill(certificate,(byte)0);}}
 private void authenticate(JSONObject q,QaPrivacyReader.Guard g)throws Exception{
  int uid=Binder.getCallingUid();String[] packages=getPackageManager().getPackagesForUid(uid);QaPrivacyReader.need(uid!=Process.myUid()&&packages!=null&&packages.length==1&&SIDECAR.equals(packages[0]),"QA_OBSERVER_EXACT_CALLER_UID_PACKAGE");
  QaPrivacyReader.need(getPackageManager().checkSignatures(getPackageName(),SIDECAR)==PackageManager.SIGNATURE_MATCH&&signer(getPackageName(),g).equals(q.getString("signerSha256"))&&signer(SIDECAR,g).equals(q.getString("signerSha256")),"QA_OBSERVER_EXACT_CALLER_SIGNER");
  ApplicationInfo own=getPackageManager().getApplicationInfo(getPackageName(),PackageManager.GET_META_DATA);QaPrivacyReader.need(own.metaData!=null&&q.getString("sourceSha").equals(own.metaData.getString("caseops.qa.observer.sourceSha")),"QA_OBSERVER_SOURCE_MISMATCH");
  String publicApk=getPackageManager().getApplicationInfo(SIDECAR,0).sourceDir;QaPrivacyReader.need(publicApk.startsWith("/data/app/")&&publicApk.equals(new File(publicApk).getCanonicalPath()),"QA_OBSERVER_CALLER_APK_PATH");g.meta();StructStat named=Os.lstat(publicApk);QaPrivacyReader.need(OsConstants.S_ISREG(named.st_mode)&&named.st_uid==1000&&named.st_nlink==1&&named.st_size>0&&named.st_size<=2097152,"QA_OBSERVER_CALLER_APK_OWNER_EXTENT");
  FileDescriptor fd=Os.open(publicApk,OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC|OsConstants.O_NONBLOCK,0);g.opened++;byte[] bytes=new byte[32768];MessageDigest sha=MessageDigest.getInstance("SHA-256");long n=0;
  try{g.meta();QaPrivacyReader.need(Arrays.equals(QaPrivacyReader.frame(named),QaPrivacyReader.frame(Os.fstat(fd))),"QA_OBSERVER_CALLER_APK_OPEN");while(true){g.check();int count=Os.read(fd,bytes,0,bytes.length);g.bytes(count,true);if(count==0)break;n+=count;QaPrivacyReader.need(n<=named.st_size,"QA_OBSERVER_CALLER_APK_GROWTH");sha.update(bytes,0,count);}g.meta();StructStat fdAfter=Os.fstat(fd);g.meta();StructStat namedAfter=Os.lstat(publicApk);QaPrivacyReader.need(n==named.st_size&&Arrays.equals(QaPrivacyReader.frame(named),QaPrivacyReader.frame(fdAfter))&&Arrays.equals(QaPrivacyReader.frame(named),QaPrivacyReader.frame(namedAfter)),"QA_OBSERVER_CALLER_APK_FINAL");StringBuilder actual=new StringBuilder();for(byte b:sha.digest())actual.append(String.format(java.util.Locale.ROOT,"%02x",b&255));QaPrivacyReader.need(actual.toString().equals(q.getString("observerApkSha256")),"QA_OBSERVER_CALLER_APK_HASH");}
  finally{Arrays.fill(bytes,(byte)0);Os.close(fd);g.closed++;}
 }
 private static void request(JSONObject q)throws Exception{
  Set<String> keys=new HashSet<>();java.util.Iterator<String> iterator=q.keys();while(iterator.hasNext())keys.add(iterator.next());QaPrivacyReader.need(keys.equals(REQUEST_KEYS)&&q.get("schemaVersion") instanceof Integer&&q.getInt("schemaVersion")==1,"QA_OBSERVER_REQUEST_SCHEMA");
  QaPrivacyReader.need(q.get("milliseconds") instanceof Integer&&q.getInt("milliseconds")>0&&q.getInt("milliseconds")<=30000&&q.get("allowQaFixtureUnstop") instanceof Boolean,"QA_OBSERVER_REQUEST_BOUNDS");
  QaPrivacyReader.need(q.get("sidecarStartElapsed") instanceof Number&&q.getLong("sidecarStartElapsed")>=0&&q.getLong("sidecarStartElapsed")<=SystemClock.elapsedRealtime()&&q.get("mainExpected") instanceof JSONObject,"QA_OBSERVER_REQUEST_MAIN_FENCE");
  JSONObject expected=q.getJSONObject("mainExpected");Set<String> mainKeys=new HashSet<>();java.util.Iterator<String> mi=expected.keys();while(mi.hasNext())mainKeys.add(mi.next());QaPrivacyReader.need(expected.get("present") instanceof Boolean&&mainKeys.equals(expected.getBoolean("present")?new HashSet<>(Arrays.asList("present","pid","uid","startTicks")):new HashSet<>(Arrays.asList("present"))),"QA_OBSERVER_REQUEST_MAIN_SCHEMA");
  if(expected.getBoolean("present"))QaPrivacyReader.need(expected.get("pid") instanceof Integer&&expected.getInt("pid")>0&&expected.get("uid") instanceof Integer&&expected.getInt("uid")==Process.myUid()&&expected.getString("startTicks").matches("[0-9]+"),"QA_OBSERVER_REQUEST_MAIN_IDENTITY");
  QaPrivacyReader.need(q.getString("requestId").matches("[a-f0-9]{32}")&&q.getString("sourceSha").matches("[a-f0-9]{40}")&&q.getString("targetApkSha256").matches("[a-f0-9]{64}")&&q.getString("observerApkSha256").matches("[a-f0-9]{64}")&&q.getString("signerSha256").matches("[a-f0-9]{64}"),"QA_OBSERVER_REQUEST_IDENTITIES");
  QaPrivacyReader.need(new HashSet<>(Arrays.asList("attest","files-snapshot","camera-snapshot")).contains(q.getString("operation"))&&"qa-main-preserved-observer-running".equals(q.getString("domain")),"QA_OBSERVER_REQUEST_SCOPE");
 }
 private void known(Lease lease,String id){QaPrivacyReader.need(lease!=null&&lease.id.equals(id)&&lease.uid==Binder.getCallingUid()&&lease.pid==Binder.getCallingPid(),"QA_OBSERVER_LEASE_IDENTITY");}
 private final Binder endpoint=new Binder(){
  @Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags){
   if(code==IBinder.INTERFACE_TRANSACTION){reply.writeString(DESCRIPTOR);return true;}
   try{data.enforceInterface(DESCRIPTOR);QaPrivacyReader.need(!data.hasFileDescriptors(),"QA_OBSERVER_FD_ARGUMENT_REFUSED");
    if(code==100){
     QaPrivacyReader.need(Binder.getCallingUid()==Process.myUid()&&Binder.getCallingPid()!=Process.myPid(),"QA_OBSERVER_MAIN_WITNESS_CALLER");int event=data.readInt();IBinder token=data.readStrongBinder();QaPrivacyReader.need(event>=0&&event<=8&&data.dataAvail()==0,"QA_OBSERVER_LIFECYCLE_ENUM");
     synchronized(LIFE){
      if(event==0){final int pid=Binder.getCallingPid();QaPrivacyReader.need(token!=null,"QA_OBSERVER_WITNESS_TOKEN");token.linkToDeath(()->witnessDied(token),0);pendingWitnessPid=pid;pendingWitness=token;lastMainCreatedElapsed=SystemClock.elapsedRealtime();}
      else if(event==8){witnessReady(token,Binder.getCallingPid());}
      else QaPrivacyReader.need(Binder.getCallingPid()==witnessPid&&token==null,"QA_OBSERVER_WITNESS_EVENT_IDENTITY");
      events++;
     }reply.writeNoException();reply.writeInt(Process.myPid());return true;
    }
    synchronized(leaseLock){
     if(code==1){QaPrivacyReader.need(active==null,"QA_OBSERVER_BUSY");String text=data.readString();IBinder token=data.readStrongBinder();QaPrivacyReader.need(text!=null&&text.getBytes(java.nio.charset.StandardCharsets.UTF_8).length<=4096&&token!=null&&data.dataAvail()==0,"QA_OBSERVER_REQUEST_EXTENT");JSONObject q=new JSONObject(text);request(q);Lease lease=new Lease();lease.id=q.getString("requestId");lease.uid=Binder.getCallingUid();lease.pid=Binder.getCallingPid();lease.token=token;lease.guard=new QaPrivacyReader.Guard(q.getString("operation"),q.getInt("milliseconds"));authenticate(q,lease.guard);active=lease;lease.death=()->{lease.guard.cancelled.set(true);synchronized(leaseLock){if(active==lease)closeLease(lease);}};lease.timeout=()->{lease.guard.cancelled.set(true);synchronized(leaseLock){if(active==lease)closeLease(lease);}};
      try{token.linkToDeath(lease.death,0);lease.linked=true;expiry.postDelayed(lease.timeout,Math.max(1,lease.guard.deadline-SystemClock.elapsedRealtime()));lease.result=QaPrivacyReader.capture(QaPrivacyService.this,q,lease.guard,sequence());reply.writeNoException();reply.writeInt(lease.result.count());return true;}
      catch(Throwable error){try{closeLease(lease);}catch(Throwable cleanup){throw new QaPrivacyReader.Fault("QA_OBSERVER_PRIMARY_AND_CLEANUP_FAILED");}throw error;}
     }

     if(code==2){String id=data.readString();int index=data.readInt();QaPrivacyReader.need(data.dataAvail()==0,"QA_OBSERVER_CHUNK_ARGUMENTS");known(active,id);active.guard.check();byte[] bytes=active.result.chunk(index);try{reply.writeNoException();reply.writeByteArray(bytes);}finally{Arrays.fill(bytes,(byte)0);}return true;}
     if(code==3){String id=data.readString();QaPrivacyReader.need(data.dataAvail()==0,"QA_OBSERVER_CLOSE_ARGUMENTS");known(active,id);Lease lease=active;closeLease(lease);reply.writeNoException();reply.writeInt(1);return true;}
     throw new QaPrivacyReader.Fault("QA_OBSERVER_TRANSACTION_REFUSED");
    }
   }catch(Throwable error){String fixed=error instanceof QaPrivacyReader.Fault?error.getMessage():"QA_OBSERVER_REQUEST_FAILED";if(fixed==null||!fixed.matches("[A-Z0-9_]+"))fixed="QA_OBSERVER_REQUEST_FAILED";reply.writeException(new SecurityException(fixed));return true;}
  }
 };
 @Override public boolean onUnbind(Intent intent){synchronized(leaseLock){if(active!=null){closeLease(active);}}return false;}
 @Override public void onDestroy(){synchronized(leaseLock){if(active!=null){closeLease(active);}}super.onDestroy();if(QaPrivacyReader.OBSERVER.equals(Application.getProcessName())&&getApplicationContext().getClass()==Application.class)Process.killProcess(Process.myPid());}
}
