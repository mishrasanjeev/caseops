package ai.caseops.mobile.qa;

import android.app.ActivityManager;
import android.app.Application;
import android.content.Context;
import android.os.Process;
import android.os.SystemClock;
import android.system.ErrnoException;
import android.system.Os;
import android.system.OsConstants;
import android.system.StructStat;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.File;
import java.io.FileDescriptor;
import java.nio.charset.StandardCharsets;
import java.nio.file.DirectoryStream;
import java.nio.file.Files;
import java.util.ArrayList;
import java.util.Arrays;
import java.util.Collections;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.atomic.AtomicBoolean;

/** Explicit QA-only read capability. Never executes a shell or creates an app directory. */
public final class QaPrivacyReader {
 public static final String APP="ai.caseops.mobile.dev.localacceptance";
 public static final String OBSERVER=APP+":privacyobserver";
 static final String[] FRAME_KEYS={"device","inode","mode","uid","gid","links","size","modifiedNs","changedNs"};
 static final int WIRE_LIMIT=67108864, CHUNK=32768;
 static final class Fault extends RuntimeException { Fault(String code){super(code);} }
 static void need(boolean value,String code){if(!value)throw new Fault(code);}
 static final class Guard {
  final long deadline; final int maxEntries,maxFiles,maxFileBytes; final AtomicBoolean cancelled=new AtomicBoolean();
  int entries,files,opened,closed; long readBytes,identityBytes;
  Guard(String op,int milliseconds){deadline=SystemClock.elapsedRealtime()+milliseconds;boolean camera="camera-snapshot".equals(op);maxEntries=camera?512:8192;maxFiles=camera?128:4096;maxFileBytes=camera?52428800:8388608;}
  void check(){need(!cancelled.get()&&SystemClock.elapsedRealtime()<deadline,"QA_OBSERVER_DEADLINE_OR_CANCELLED");}
  void meta(){check();need(++entries<=maxEntries,"QA_OBSERVER_ENTRY_BOUND");}
  void bytes(int count,boolean identity){check();need(count>=0&&readBytes+identityBytes+count<=WIRE_LIMIT,"QA_OBSERVER_BYTE_BOUND");if(identity)identityBytes+=count;else readBytes+=count;}
 }
 static String nano(long seconds,long nanos){return java.math.BigInteger.valueOf(seconds).multiply(java.math.BigInteger.valueOf(1000000000L)).add(java.math.BigInteger.valueOf(nanos)).toString();}
 static String[] frame(StructStat s){return new String[]{Long.toString(s.st_dev),Long.toString(s.st_ino),Integer.toString(s.st_mode),Integer.toString(s.st_uid),Integer.toString(s.st_gid),Long.toString(s.st_nlink),Long.toString(s.st_size),nano(s.st_mtim.tv_sec,s.st_mtim.tv_nsec),nano(s.st_ctim.tv_sec,s.st_ctim.tv_nsec)};}
 static StructStat named(String path,Guard g,boolean absent)throws Exception{
  g.meta();try{return Os.lstat(path);}catch(ErrnoException error){if(absent&&error.errno==OsConstants.ENOENT)return null;throw new Fault("QA_OBSERVER_STAT_ERRNO_"+error.errno);}
 }
 static String canonical(String path,Guard g)throws Exception{g.meta();need(path.equals(new File(path).getCanonicalPath()),"QA_OBSERVER_CANONICAL_PATH");return path;}
 static JSONArray namespace(String path,String ownedRoot,Guard g)throws Exception{
  JSONArray rows=new JSONArray();File p=new File(path).getParentFile();
  while(p!=null){String name=p.getPath();StructStat s=named(name,g,name.startsWith(ownedRoot+"/"));if(s==null){rows.put(new JSONObject().put("path",name).put("owned",true).put("frame",JSONObject.NULL));p=p.getParentFile();continue;}need(OsConstants.S_ISDIR(s.st_mode),"QA_OBSERVER_NAMESPACE_DIRECTORY");String[] f=frame(s);
   boolean owned=name.equals(ownedRoot)||name.startsWith(ownedRoot+"/");JSONArray identity=new JSONArray();int[] positions=owned?new int[]{0,1,2,3,4,5,6,7,8}:new int[]{0,1,2,3,4};for(int position:positions)identity.put(f[position]);rows.put(new JSONObject().put("path",name).put("owned",owned).put("frame",identity));p=p.getParentFile();}
  return rows;
 }
 static final class Entry { final String path;final String[] initial;final boolean directory;final String canonical;String[] finalFrame;JSONObject opened;
  Entry(String p,StructStat s,String c){path=p;initial=frame(s);directory=OsConstants.S_ISDIR(s.st_mode);canonical=c;}
  JSONObject json()throws Exception{return new JSONObject().put("path",path).put("kind",directory?"directory":"file").put("before",new JSONArray(Arrays.asList(initial))).put("after",new JSONArray(Arrays.asList(finalFrame))).put("canonical",canonical).put("opened",opened==null?JSONObject.NULL:opened);}
 }
 static final class Root {final String name,path;final boolean required;final int depth;Root(String n,String p,boolean r,int d){name=n;path=p;required=r;depth=d;} }
 static Map<String,Entry> inventory(Root root,int uid,Guard g)throws Exception{
  LinkedHashMap<String,Entry> result=new LinkedHashMap<>();StructStat top=named(root.path,g,!root.required);if(top==null)return result;
  need(OsConstants.S_ISDIR(top.st_mode)&&top.st_uid==uid,"QA_OBSERVER_ROOT_OWNER");List<String> todo=new ArrayList<>();todo.add(root.path);
  while(!todo.isEmpty()){
   g.check();String p=todo.remove(todo.size()-1);StructStat s=named(p,g,false);need(s.st_dev==top.st_dev&&s.st_uid==uid,"QA_OBSERVER_SCOPE_OWNER_DEVICE");need(OsConstants.S_ISDIR(s.st_mode)||OsConstants.S_ISREG(s.st_mode),"QA_OBSERVER_LINK_OR_TYPE");String relative=p.substring(root.path.length());need(relative.isEmpty()||relative.substring(1).split("/",-1).length<=root.depth,"QA_OBSERVER_DEPTH_BOUND");
   need(!result.containsKey(p),"QA_OBSERVER_DUPLICATE_PATH");Entry entry=new Entry(p,s,canonical(p,g));result.put(p,entry);
   if(!entry.directory){need(s.st_nlink==1,"QA_OBSERVER_SINGLE_LINK");continue;}
   FileDescriptor fd=Os.open(p,OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC|OsConstants.O_NONBLOCK,0);g.opened++;
   try {g.meta();StructStat opened=Os.fstat(fd);need(OsConstants.S_ISDIR(opened.st_mode)&&Arrays.equals(frame(s),frame(opened)),"QA_OBSERVER_DIRECTORY_FD_CHANGED");List<String> children=new ArrayList<>();
    g.meta();DirectoryStream<java.nio.file.Path> stream=Files.newDirectoryStream(new File(p).toPath());g.opened++;try{
     for(java.nio.file.Path child:stream){g.meta();String name=child.getFileName().toString();need(!name.isEmpty()&&!name.equals(".")&&!name.equals("..")&&!name.contains("/")&&!name.contains("\\")&&!name.matches(".*[\\x00-\\x1f\\x7f].*"),"QA_OBSERVER_CHILD_NAME");need(!children.contains(name),"QA_OBSERVER_DUPLICATE_CHILD");children.add(name);}
    }
    finally{stream.close();g.closed++;}
    Collections.sort(children);for(int i=children.size()-1;i>=0;i--)todo.add(p+"/"+children.get(i));
    g.meta();need(Arrays.equals(frame(s),frame(Os.fstat(fd)))&&Arrays.equals(frame(s),frame(named(p,g,false))),"QA_OBSERVER_DIRECTORY_CHANGED");
   }finally{Os.close(fd);g.closed++;}
  }
  need(result.containsKey(root.path),"QA_OBSERVER_ROOT_PRESENT");return result;
 }
 static final class Body { final byte[] data;final int size;Body(byte[] d,int n){data=d;size=n;}void wipe(){Arrays.fill(data,(byte)0);} }
 static Body read(Entry entry,Root root,int uid,Guard g)throws Exception{
  StructStat before=named(entry.path,g,false);need(Arrays.equals(entry.initial,frame(before))&&OsConstants.S_ISREG(before.st_mode)&&before.st_uid==uid&&before.st_nlink==1,"QA_OBSERVER_FILE_BEFORE");need(before.st_size>=0&&before.st_size<=g.maxFileBytes&&g.readBytes+g.identityBytes+before.st_size<=WIRE_LIMIT&&++g.files<=g.maxFiles,"QA_OBSERVER_FILE_BOUND");
  JSONArray ns=namespace(entry.path,root.path,g);byte[] data=new byte[(int)before.st_size+1];FileDescriptor fd=Os.open(entry.path,OsConstants.O_RDONLY|OsConstants.O_NOFOLLOW|OsConstants.O_CLOEXEC|OsConstants.O_NONBLOCK,0);g.opened++;boolean retained=false;
  try {
   g.meta();String[] first=frame(Os.fstat(fd));need(Arrays.equals(entry.initial,first),"QA_OBSERVER_OPEN_CHANGED");int pos=0;
   while(pos<data.length){g.check();int n=Os.read(fd,data,pos,Math.min(CHUNK,data.length-pos));need(n>=0,"QA_OBSERVER_READ_RESULT");g.bytes(n,false);if(n==0)break;pos+=n;}
   g.meta();String[] last=frame(Os.fstat(fd));String[] finalPath=frame(named(entry.path,g,false));JSONArray after=namespace(entry.path,root.path,g);
   need(pos==before.st_size&&Arrays.equals(first,last)&&Arrays.equals(first,finalPath)&&ns.toString().equals(after.toString())&&canonical(entry.path,g).equals(entry.canonical),"QA_OBSERVER_FINAL_FILE_CHANGED");
   entry.opened=new JSONObject().put("pathBefore",new JSONArray(Arrays.asList(entry.initial))).put("fdBefore",new JSONArray(Arrays.asList(first))).put("fdAfter",new JSONArray(Arrays.asList(last))).put("pathAfter",new JSONArray(Arrays.asList(finalPath))).put("namespaceBefore",ns).put("namespaceAfter",after).put("length",pos).put("fdClosed",true);retained=true;return new Body(data,pos);
  }finally{Os.close(fd);g.closed++;if(!retained)Arrays.fill(data,(byte)0);}
 }
 static JSONObject main(Context context,Guard g)throws Exception{
  g.meta();ActivityManager am=(ActivityManager)context.getSystemService(Context.ACTIVITY_SERVICE);List<ActivityManager.RunningAppProcessInfo> rows=am.getRunningAppProcesses();ActivityManager.RunningAppProcessInfo selected=null;
  if(rows!=null)for(ActivityManager.RunningAppProcessInfo row:rows)if(APP.equals(row.processName)){need(selected==null&&row.uid==Process.myUid(),"QA_OBSERVER_MAIN_PROCESS_AMBIGUOUS");selected=row;}
  if(selected==null)return new JSONObject().put("present",false);
  String p="/proc/"+selected.pid+"/stat";FileDescriptor fd=Os.open(p,OsConstants.O_RDONLY|OsConstants.O_CLOEXEC|OsConstants.O_NOFOLLOW|OsConstants.O_NONBLOCK,0);g.opened++;byte[] bytes=new byte[4097];
  try{g.meta();StructStat first=Os.fstat(fd);need(first.st_uid==Process.myUid(),"QA_OBSERVER_MAIN_PROC_OWNER");int n=Os.read(fd,bytes,0,bytes.length);g.bytes(n,true);need(n>0&&n<bytes.length,"QA_OBSERVER_MAIN_PROC_BOUND");String text=new String(bytes,0,n,StandardCharsets.US_ASCII);int close=text.lastIndexOf(')');need(close>0,"QA_OBSERVER_MAIN_PROC_FRAME");String[] fields=text.substring(close+2).trim().split(" +");need(fields.length>19&&fields[19].matches("[0-9]+"),"QA_OBSERVER_MAIN_BIRTH");return new JSONObject().put("present",true).put("pid",selected.pid).put("uid",selected.uid).put("startTicks",fields[19]);}
  finally{Arrays.fill(bytes,(byte)0);Os.close(fd);g.closed++;}
 }
 static boolean sameMain(JSONObject a,JSONObject b)throws Exception{return a.getBoolean("present")==b.getBoolean("present")&&(!a.getBoolean("present")||(a.getInt("pid")==b.getInt("pid")&&a.getInt("uid")==b.getInt("uid")&&a.getString("startTicks").equals(b.getString("startTicks"))));}
 static final class Result {
  final byte[] header;final List<Body> bodies;final int size;int next;
  Result(JSONObject metadata,List<Body> values)throws Exception{header=metadata.toString().getBytes(StandardCharsets.UTF_8);bodies=values;long n=12L+header.length;for(Body b:values)n+=b.size;need(n<=WIRE_LIMIT,"QA_OBSERVER_WIRE_BOUND");size=(int)n;}
  int count(){return(size+CHUNK-1)/CHUNK;}
  byte[] chunk(int index){need(index==next&&index<count(),"QA_OBSERVER_CHUNK_SEQUENCE");next++;int begin=index*CHUNK,len=Math.min(CHUNK,size-begin);byte[] out=new byte[len];int global=0,pos=0;byte[] magic="CPQAOBS1".getBytes(StandardCharsets.US_ASCII);byte[] length=new byte[]{(byte)(header.length>>>24),(byte)(header.length>>>16),(byte)(header.length>>>8),(byte)header.length};List<byte[]> buffers=new ArrayList<>();List<Integer> sizes=new ArrayList<>();buffers.add(magic);sizes.add(8);buffers.add(length);sizes.add(4);buffers.add(header);sizes.add(header.length);for(Body b:bodies){buffers.add(b.data);sizes.add(b.size);}for(int j=0;j<buffers.size()&&pos<len;j++){int n=sizes.get(j);if(begin<global+n&&begin+len>global){int start=Math.max(0,begin-global),count=Math.min(n-start,len-pos);System.arraycopy(buffers.get(j),start,out,pos,count);pos+=count;}global+=n;}need(pos==len,"QA_OBSERVER_CHUNK_EXTENT");return out;}
  void wipe(){Arrays.fill(header,(byte)0);for(Body b:bodies)b.wipe();}
 }
 static Result capture(Context context,JSONObject request,Guard g,long epoch)throws Exception{
  String op=request.getString("operation");int uid=Process.myUid();need(APP.equals(context.getPackageName())&&OBSERVER.equals(Application.getProcessName())&&context.getApplicationContext().getClass()==Application.class&&uid>=10000&&uid<100000,"QA_OBSERVER_ACTUAL_ACCESS_IDENTITY");
  String data=context.getApplicationInfo().dataDir;need(data.equals("/data/user/0/"+APP),"QA_OBSERVER_DATA_ROOT");JSONObject before=main(context,g);need(sameMain(before,request.getJSONObject("mainExpected")),"QA_OBSERVER_MAIN_EXPECTATION_CHANGED");need(before.getBoolean("present")||QaPrivacyService.lastMainCreated()<request.getLong("sidecarStartElapsed"),"QA_OBSERVER_COLD_MAIN_WAS_STARTED");QaPrivacyService.requireWitness(before,g);epoch=QaPrivacyService.sequence();List<Root> roots=new ArrayList<>();boolean camera=op.equals("camera-snapshot");
  if(op.equals("files-snapshot")){roots.add(new Root("app-data",data,true,16));roots.add(new Root("external-app-data","/storage/emulated/0/Android/data/"+APP,false,16));}
  else if(camera){roots.add(new Root("camera",data+"/cache/ImagePicker",false,1));}
  else need(op.equals("attest"),"QA_OBSERVER_OPERATION");
  List<Body> bodies=new ArrayList<>();JSONArray inventories=new JSONArray(),records=new JSONArray();boolean retained=false;
  try {
   StructStat app=named(data,g,false);need(OsConstants.S_ISDIR(app.st_mode)&&app.st_uid==uid,"QA_OBSERVER_APP_ROOT_OWNER");JSONObject rootFacts=new JSONObject().put("path",data).put("frame",new JSONArray(Arrays.asList(frame(app))));
   StructStat ext=named("/storage/emulated/0/Android/data/"+APP,g,true);need(ext==null||(OsConstants.S_ISDIR(ext.st_mode)&&ext.st_uid==uid),"QA_OBSERVER_EXTERNAL_ROOT_OWNER");JSONObject external=ext==null?null:new JSONObject().put("path","/storage/emulated/0/Android/data/"+APP).put("frame",new JSONArray(Arrays.asList(frame(ext))));
   for(Root root:roots){JSONArray ns=namespace(root.path,data,g);Map<String,Entry> first=inventory(root,uid,g);List<String> initial=new ArrayList<>(first.keySet());Collections.sort(initial);long rootOffset=0;
    for(String p:initial){Entry e=first.get(p);if(!e.directory){if(camera)need(new File(p).getName().matches("(?i)[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}\\.(?:jpg|jpeg|png)"),"QA_OBSERVER_CAMERA_NAME");Body body=read(e,root,uid,g);bodies.add(body);e.opened.put("bodyIndex",bodies.size()-1);rootOffset+=body.size;}}
    Map<String,Entry> last=inventory(root,uid,g);List<String> fin=new ArrayList<>(last.keySet());Collections.sort(fin);need(initial.equals(fin),"QA_OBSERVER_MEMBERSHIP_CHANGED");
    for(String p:fin){Entry e=first.get(p);e.finalFrame=last.get(p).initial;need(Arrays.equals(e.initial,e.finalFrame)&&e.canonical.equals(last.get(p).canonical),"QA_OBSERVER_FINAL_METADATA_CHANGED");records.put(e.json());}
    List<String> directories=new ArrayList<>();for(String p:fin)if(first.get(p).directory)directories.add(p);Collections.sort(directories,(a,b)->Integer.compare(b.length(),a.length()));for(String p:directories)need(Arrays.equals(first.get(p).initial,frame(named(p,g,false))),"QA_OBSERVER_ROOT_LAST_CHANGED");
    JSONArray nsAfter=namespace(root.path,data,g);need(ns.toString().equals(nsAfter.toString()),"QA_OBSERVER_FINAL_NAMESPACE_CHANGED");inventories.put(new JSONObject().put("name",root.name).put("root",root.path).put("initial",new JSONArray(initial)).put("final",new JSONArray(fin)).put("namespaceBefore",ns).put("namespaceAfter",nsAfter));
   }
   QaPrivacyService.requireWitness(before,g);JSONObject after=main(context,g);need(before.toString().equals(after.toString())&&epoch==QaPrivacyService.sequence(),"QA_OBSERVER_MAIN_LIFECYCLE_CHANGED");need(g.opened==g.closed,"QA_OBSERVER_FD_CLOSURE");
   JSONObject metadata=new JSONObject().put("schemaVersion",1).put("kind","caseops-qa-observer-composite").put("complete",true).put("requestId",request.getString("requestId")).put("operation",op).put("sourceSha",request.getString("sourceSha")).put("targetApkSha256",request.getString("targetApkSha256")).put("observerApkSha256",request.getString("observerApkSha256")).put("signerSha256",request.getString("signerSha256")).put("callerUid",android.os.Binder.getCallingUid()).put("callerPid",android.os.Binder.getCallingPid()).put("mainExpected",request.getJSONObject("mainExpected")).put("sidecarStartElapsed",request.getLong("sidecarStartElapsed")).put("lastMainCreatedElapsed",QaPrivacyService.lastMainCreated()).put("packageUid",uid).put("observerPid",Process.myPid()).put("observerProcess",Application.getProcessName()).put("applicationClass",context.getApplicationContext().getClass().getName()).put("mainBefore",before).put("mainAfter",after).put("lifecycleSequenceBefore",epoch).put("lifecycleSequenceAfter",sequence()).put("appData",rootFacts).put("externalAppData",external==null?JSONObject.NULL:external).put("inventories",inventories).put("records",records).put("entries",g.entries).put("privateBytesRead",g.readBytes).put("identityBytesRead",g.identityBytes).put("fdsOpened",g.opened).put("fdsClosed",g.closed).put("providerOriginalsRead",false).put("deviceFilesDeleted",false).put("appRestarted",false).put("fullPackageForceStoppedStateCertified",false);
   Result result=new Result(metadata,bodies);retained=true;return result;
  }finally{if(!retained)for(Body body:bodies)body.wipe();}
 }
 private static long sequence(){return QaPrivacyService.sequence();}
}
