package ai.caseops.qa.privacyobserver;

import android.app.Instrumentation;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageInfo;
import android.content.pm.PackageManager;
import android.os.Binder;
import android.os.Bundle;
import android.os.IBinder;
import android.os.Parcel;
import android.os.SystemClock;
import org.json.JSONObject;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.util.Arrays;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;

/** Self-target only. No UiAutomation, AndroidJUnitRunner, shell, app launch or private path access. */
public final class ObserverInstrumentation extends Instrumentation {
 private static final String APP="ai.caseops.mobile.dev.localacceptance", SELF="ai.caseops.qa.privacyobserver", DESCRIPTOR="ai.caseops.qa.private-observer.v1";
 private String requestText;private final CountDownLatch connected=new CountDownLatch(1);private volatile IBinder service;private boolean bound;private long deadline;private int identityBytes;
 private final IBinder lifetime=new Binder();
 private static void need(boolean ok,String label){if(!ok)throw new SecurityException(label);}
 private final ServiceConnection connection=new ServiceConnection(){public void onServiceConnected(ComponentName name,IBinder binder){service=binder;connected.countDown();}public void onServiceDisconnected(ComponentName name){service=null;connected.countDown();}};
 @Override public void onCreate(Bundle arguments){super.onCreate(arguments);if(arguments!=null&&arguments.keySet().size()==1&&arguments.get("caseopsRequest") instanceof String)requestText=arguments.getString("caseopsRequest");start();}
 private String signer(Context context,String pkg)throws Exception{PackageInfo info=context.getPackageManager().getPackageInfo(pkg,PackageManager.GET_SIGNING_CERTIFICATES);need(info.signingInfo!=null&&!info.signingInfo.hasMultipleSigners()&&info.signingInfo.getApkContentsSigners().length==1,"QA_SIDECAR_SINGLE_SIGNER");byte[] raw=info.signingInfo.getApkContentsSigners()[0].toByteArray();try{identityBytes+=raw.length;need(raw.length>0&&raw.length<=16384&&identityBytes<=32768,"QA_SIDECAR_CERTIFICATE_BOUND");return hex(MessageDigest.getInstance("SHA-256").digest(raw));}finally{Arrays.fill(raw,(byte)0);}}
 private static String hex(byte[] bytes){StringBuilder out=new StringBuilder();for(byte value:bytes)out.append(String.format(java.util.Locale.ROOT,"%02x",value&255));return out.toString();}
 private Parcel begin(JSONObject request)throws Exception{Parcel in=Parcel.obtain(),out=Parcel.obtain();try{in.writeInterfaceToken(DESCRIPTOR);in.writeString(request.toString());in.writeStrongBinder(lifetime);need(service!=null&&service.transact(1,in,out,0),"QA_SIDECAR_BEGIN_TRANSPORT");out.readException();return out;}catch(Throwable error){out.recycle();throw error;}finally{in.recycle();}}
 private byte[] chunk(String id,int index)throws Exception{Parcel in=Parcel.obtain(),out=Parcel.obtain();try{in.writeInterfaceToken(DESCRIPTOR);in.writeString(id);in.writeInt(index);need(service!=null&&service.transact(2,in,out,0),"QA_SIDECAR_CHUNK_TRANSPORT");out.readException();byte[] bytes=out.createByteArray();need(bytes!=null&&bytes.length>0&&bytes.length<=32768&&out.dataAvail()==0,"QA_SIDECAR_CHUNK_BOUND");return bytes;}finally{in.recycle();out.recycle();}}
 private void close(String id)throws Exception{Parcel in=Parcel.obtain(),out=Parcel.obtain();try{in.writeInterfaceToken(DESCRIPTOR);in.writeString(id);need(service!=null&&service.transact(3,in,out,0),"QA_SIDECAR_CLOSE_TRANSPORT");out.readException();need(out.readInt()==1&&out.dataAvail()==0,"QA_SIDECAR_CLOSE_ACK");}finally{in.recycle();out.recycle();}}
 @Override public void onStart(){
  Bundle result=new Bundle();String id=null;boolean begun=false,closed=false;Context context=getTargetContext();
  try{
   need(SELF.equals(context.getPackageName())&&requestText!=null&&requestText.getBytes(StandardCharsets.UTF_8).length<=4096,"QA_SIDECAR_REQUEST");JSONObject q=new JSONObject(requestText);id=q.getString("requestId");need(id.matches("[a-f0-9]{32}")&&q.getString("signerSha256").matches("[a-f0-9]{64}"),"QA_SIDECAR_IDENTITY");int ms=q.getInt("milliseconds");need(ms>0&&ms<=30000,"QA_SIDECAR_DEADLINE");long started=SystemClock.elapsedRealtime();deadline=started+ms;
   PackageManager pm=context.getPackageManager();ApplicationInfo target=pm.getApplicationInfo(APP,PackageManager.GET_META_DATA);need((target.flags&ApplicationInfo.FLAG_DEBUGGABLE)==0&&target.uid!=android.os.Process.myUid()&&signer(context,APP).equals(q.getString("signerSha256"))&&signer(context,SELF).equals(q.getString("signerSha256")),"QA_SIDECAR_SAME_SIGNED_NONDEBUGGABLE_TARGET");
   boolean stoppedBefore=(target.flags&ApplicationInfo.FLAG_STOPPED)!=0;need(!stoppedBefore||q.getBoolean("allowQaFixtureUnstop"),"QA_SIDECAR_FIXTURE_UNSTOP_NOT_AUTHORIZED");result.putString("caseops.packageStoppedBefore",Boolean.toString(stoppedBefore));
   q.put("sidecarStartElapsed",started);q.put("milliseconds",Math.max(1,(int)(deadline-SystemClock.elapsedRealtime())));Intent intent=new Intent();intent.setComponent(new ComponentName(APP,"ai.caseops.mobile.qa.QaPrivacyService"));bound=context.bindService(intent,connection,Context.BIND_AUTO_CREATE);need(bound&&connected.await(Math.max(1,deadline-SystemClock.elapsedRealtime()),TimeUnit.MILLISECONDS)&&service!=null,"QA_SIDECAR_BIND_UNAVAILABLE");
   need(SystemClock.elapsedRealtime()<deadline,"QA_SIDECAR_DEADLINE");q.put("milliseconds",(int)(deadline-SystemClock.elapsedRealtime()));
   begun=true;Parcel response=begin(q);int count;try{count=response.readInt();need(count>0&&count<=2048&&response.dataAvail()==0,"QA_SIDECAR_CHUNK_COUNT");}finally{response.recycle();}MessageDigest sha=MessageDigest.getInstance("SHA-256");int total=0;
   for(int i=0;i<count;i++){need(SystemClock.elapsedRealtime()<deadline,"QA_SIDECAR_DEADLINE");byte[] data=chunk(id,i);try{total+=data.length;need(total<=67108864,"QA_SIDECAR_WIRE_BOUND");sha.update(data);Bundle status=new Bundle();status.putString("caseops.requestId",id);status.putInt("caseops.sequence",i);status.putByteArray("caseops.chunk",data);sendStatus(0,status);}finally{Arrays.fill(data,(byte)0);}}
   close(id);closed=true;result.putString("caseops.packetSha256",hex(sha.digest()));result.putInt("caseops.chunkCount",count);result.putString("caseops.requestId",id);result.putString("caseops.complete","true");result.putString("caseops.leaseClosed","true");result.putInt("caseops.sidecarIdentityBytes",identityBytes);
   ApplicationInfo after=pm.getApplicationInfo(APP,0);result.putString("caseops.packageStoppedAfter",Boolean.toString((after.flags&ApplicationInfo.FLAG_STOPPED)!=0));
  }catch(Throwable error){result.putString("caseops.complete","false");String fixed=error instanceof SecurityException?error.getMessage():null;result.putString("caseops.error",fixed!=null&&fixed.matches("QA_(?:OBSERVER|SIDECAR)_[A-Z0-9_]+")?fixed:"QA_SIDECAR_OBSERVATION_FAILED");}
  finally{
   if(begun&&!closed)try{close(id);closed=true;}catch(Throwable ignored){result.putString("caseops.cleanupFailure","QA_SIDECAR_LEASE_CLOSE_UNCONFIRMED");}
   if(bound)try{context.unbindService(connection);}catch(Throwable ignored){result.putString("caseops.cleanupFailure","QA_SIDECAR_UNBIND_UNCONFIRMED");}
   requestText=null;service=null;finish("true".equals(result.getString("caseops.complete"))&&closed?0:1,result);
  }
 }
}
