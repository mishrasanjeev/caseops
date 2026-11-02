package ai.caseops.mobile.qa;

import android.app.Activity;
import android.app.Application;
import android.content.ComponentName;
import android.content.Context;
import android.content.Intent;
import android.content.ServiceConnection;
import android.os.Binder;
import android.os.Bundle;
import android.os.Handler;
import android.os.HandlerThread;
import android.os.IBinder;
import android.os.Parcel;
import java.util.ArrayDeque;
import java.util.concurrent.CountDownLatch;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicInteger;

/** Fixed labels only, off the UI thread. Registration has a separate ready ACK. */
public final class QaLifecycleWitness implements Application.ActivityLifecycleCallbacks {
 private final Handler handler;private final CountDownLatch registered=new CountDownLatch(1);private final AtomicInteger pending=new AtomicInteger();private final ArrayDeque<Integer> waiting=new ArrayDeque<>();private volatile IBinder endpoint;private volatile int observerPid=-1;private volatile boolean failed,ready;
 private QaLifecycleWitness(){HandlerThread thread=new HandlerThread("caseops-qa-lifecycle");thread.start();handler=new Handler(thread.getLooper());}
 public static boolean install(Application app){
  if(!QaPrivacyReader.APP.equals(Application.getProcessName()))return false;
  try{QaLifecycleWitness witness=new QaLifecycleWitness();app.registerActivityLifecycleCallbacks(witness);Intent intent=new Intent();intent.setComponent(new ComponentName(QaPrivacyReader.APP,"ai.caseops.mobile.qa.QaPrivacyService"));
   if(!app.bindService(intent,Context.BIND_AUTO_CREATE,command->witness.handler.post(command),witness.connection))return false;
   return witness.registered.await(1000,TimeUnit.MILLISECONDS)&&witness.ready&&!witness.failed;
  }catch(Throwable ignored){return false;}
 }
 private final Binder drain=new Binder(){@Override protected boolean onTransact(int code,Parcel data,Parcel reply,int flags){
  try{data.enforceInterface(QaPrivacyService.WITNESS);int milliseconds=data.readInt();if(code!=1||Binder.getCallingPid()!=observerPid||Binder.getCallingUid()!=android.os.Process.myUid()||milliseconds<=0||milliseconds>1000||data.dataAvail()!=0)throw new SecurityException("QA_WITNESS_CALLER");CountDownLatch latch=new CountDownLatch(1);handler.post(latch::countDown);boolean drained=latch.await(milliseconds,TimeUnit.MILLISECONDS)&&!failed&&ready&&pending.get()==0;reply.writeNoException();reply.writeInt(drained?1:0);return true;}catch(Throwable ignored){reply.writeException(new SecurityException("QA_WITNESS_UNAVAILABLE"));return true;}
 }};
 private int send(int event)throws Exception{
  Parcel request=Parcel.obtain(),reply=Parcel.obtain();try{IBinder target=endpoint;if(target==null)throw new SecurityException("QA_WITNESS_MISSING");request.writeInterfaceToken(QaPrivacyService.DESCRIPTOR);request.writeInt(event);request.writeStrongBinder(event==0||event==8?drain:null);if(!target.transact(100,request,reply,0))throw new SecurityException("QA_WITNESS_TRANSPORT");reply.readException();int pid=reply.readInt();if(observerPid!=-1&&observerPid!=pid)throw new SecurityException("QA_WITNESS_REPLACED");return pid;}finally{request.recycle();reply.recycle();}
 }
 private final ServiceConnection connection=new ServiceConnection(){
  public void onServiceConnected(ComponentName name,IBinder binder){endpoint=binder;try{observerPid=send(0);send(8);ready=true;while(!waiting.isEmpty()){send(waiting.removeFirst());pending.decrementAndGet();}}catch(Throwable ignored){failed=true;}finally{registered.countDown();}}
  public void onServiceDisconnected(ComponentName name){endpoint=null;observerPid=-1;ready=false;failed=true;}
 };
 private void emit(int event){
  if(failed)return;if(pending.incrementAndGet()>64){failed=true;pending.decrementAndGet();return;}
  handler.post(()->{if(failed)return;if(!ready){waiting.addLast(event);return;}try{send(event);}catch(Throwable ignored){failed=true;}finally{pending.decrementAndGet();}});
 }
 public void onActivityCreated(Activity a,Bundle state){emit(1);}public void onActivityStarted(Activity a){emit(2);}public void onActivityResumed(Activity a){emit(3);}public void onActivityPaused(Activity a){emit(4);}public void onActivityStopped(Activity a){emit(5);}public void onActivitySaveInstanceState(Activity a,Bundle state){emit(6);}public void onActivityDestroyed(Activity a){emit(7);}
}
