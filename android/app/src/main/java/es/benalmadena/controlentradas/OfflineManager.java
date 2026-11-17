package es.benalmadena.controlentradas;

import android.content.Context;
import android.content.SharedPreferences;
import android.util.Base64;
import org.json.JSONArray;
import org.json.JSONObject;
import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.InputStream;
import java.io.OutputStream;
import java.io.FileInputStream;
import java.net.Inet4Address;
import java.net.NetworkInterface;
import java.net.ServerSocket;
import java.net.Socket;
import java.nio.charset.StandardCharsets;
import java.security.KeyFactory;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.security.Signature;
import java.security.spec.X509EncodedKeySpec;
import java.util.Enumeration;
import java.util.HashMap;
import java.util.Map;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/** Offline JSON package signed by Windows; optional Android coordinator in local Wi-Fi/hotspot.
 * No cloud or fixed Windows IP. All coordinator approvals share one synchronized state.
 */
public final class OfflineManager {
    public static final int PORT = 8766;
    private final Context context;
    private final SharedPreferences prefs;
    private final File stored;
    private JSONObject data;
    private String publicKey = "";
    private final Map<String,JSONObject> tickets = new HashMap<>();
    private ServerSocket server;
    private final ExecutorService threads = Executors.newCachedThreadPool();

    public OfflineManager(Context context) {
        this.context=context.getApplicationContext();
        prefs=this.context.getSharedPreferences("offline_v1",Context.MODE_PRIVATE);
        stored=new File(this.context.getFilesDir(),"signed_event_v1.json");
        if(stored.isFile()) try {
            byte[] bytes=readAll(new FileInputStream(stored),4_000_000);
            load(new String(bytes, StandardCharsets.UTF_8), false);
        } catch(Exception ignored) { data=null; }
    }
    private static byte[] decodeUrl(String v) {
        return Base64.decode(v,Base64.URL_SAFE|Base64.NO_PADDING|Base64.NO_WRAP);
    }
    private static byte[] readAll(InputStream in,int max) throws Exception {
        try(InputStream input=in; ByteArrayOutputStream b=new ByteArrayOutputStream()) {
            byte[] block=new byte[8192];int n;
            while((n=input.read(block))!=-1){b.write(block,0,n);if(b.size()>max)throw new Exception("Archivo demasiado grande");}
            return b.toByteArray();
        }
    }
    public static String fingerprint(String pub) throws Exception {
        byte[] hash=MessageDigest.getInstance("SHA-256").digest(Base64.decode(pub,Base64.DEFAULT));
        StringBuilder sb=new StringBuilder();
        for(int i=0;i<8;i++)sb.append(String.format("%02X",hash[i]));
        return sb.toString();
    }
    public synchronized JSONObject load(String raw,boolean persist) throws Exception {
        if(raw.length()>4_000_000)throw new Exception("Paquete JSON demasiado grande");
        JSONObject pack=new JSONObject(raw);
        if(!"CE-OFFLINE-1".equals(pack.optString("format")))throw new Exception("No es un JSON de Control de Entradas");
        String pub=pack.getString("public_key"), encoded=pack.getString("payload");
        String old=prefs.getString("trusted_key","");
        if(!old.isEmpty() && !old.equals(pub))throw new Exception("Clave de firma diferente al equipo de confianza");
        PublicKey key=KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(Base64.decode(pub,Base64.DEFAULT)));
        Signature check=Signature.getInstance("SHA256withECDSA");
        check.initVerify(key);check.update(encoded.getBytes(StandardCharsets.US_ASCII));
        if(!check.verify(decodeUrl(pack.getString("signature"))))throw new Exception("Firma del archivo JSON inválida");
        JSONObject decoded=new JSONObject(new String(decodeUrl(encoded),StandardCharsets.UTF_8));
        if(decoded.optInt("version")!=1)throw new Exception("Versión de archivo no compatible");
        JSONObject event=decoded.getJSONObject("event");
        JSONArray array=decoded.getJSONArray("tickets");
        if(array.length()>10000 || event.optString("id").isEmpty())throw new Exception("Datos de función inválidos");
        HashMap<String,JSONObject> byId=new HashMap<>();
        for(int i=0;i<array.length();i++){
            JSONObject t=array.getJSONObject(i);
            if(t.optString("id").isEmpty() || byId.put(t.getString("id"),t)!=null)throw new Exception("Identificador de entrada inválido o duplicado");
        }
        if(persist){
            // A signed new inventory is the authority for this event. A reimport
            // of identical signed payload preserves actual local access history.
            String incoming=encoded;
            String previous=prefs.getString("inventory_payload_"+event.optString("id"),"");
            if(previous.isEmpty() && stored.isFile()){
                try{
                    JSONObject former=new JSONObject(new String(readAll(new FileInputStream(stored),4_000_000),StandardCharsets.UTF_8));
                    previous=former.optString("payload","");
                }catch(Exception ignored){}
            }
            if(!previous.isEmpty() && !previous.equals(incoming)){
                String oldPrefix="used_"+event.optString("id")+"_";
                String timePrefix="used_time_"+event.optString("id")+"_";
                SharedPreferences.Editor reset=prefs.edit();
                for(String k:prefs.getAll().keySet()){
                    if(k.startsWith(oldPrefix)||k.startsWith(timePrefix))reset.remove(k);
                }
                if(!reset.commit())throw new Exception("No se pudo cambiar el inventario de entradas");
            }
            try(FileOutputStream out=new FileOutputStream(stored,false)){out.write(raw.getBytes(StandardCharsets.UTF_8));out.getFD().sync();}
            prefs.edit().putString("trusted_key",pub)
                .putString("inventory_payload_"+event.optString("id"),incoming).commit();
        }
        data=decoded;publicKey=pub;tickets.clear();tickets.putAll(byId);
        return event;
    }
    public synchronized String importedKey(){ return publicKey; }
    public synchronized boolean hasPackage(){ return data!=null; }
    public synchronized File storedPackage() throws Exception {
        if(data==null || !stored.isFile())throw new Exception("No hay JSON firmado para compartir");
        return stored;
    }
    public synchronized String eventId(){ return data==null?"":data.optJSONObject("event").optString("id"); }
    public synchronized JSONObject event(){ return data==null?null:data.optJSONObject("event"); }
    public synchronized int ticketCount(){ return tickets.size(); }
    public synchronized JSONArray ticketList() {
        JSONArray rows = new JSONArray();
        if(data==null)return rows;
        java.util.ArrayList<JSONObject> ordered=new java.util.ArrayList<>(tickets.values());
        ordered.sort((a,b)->Integer.compare(a.optInt("number"),b.optInt("number")));
        String eid=eventId();
        for(JSONObject t:ordered){
            JSONObject item=new JSONObject();
            try{
                item.put("number",t.optInt("number"));
                item.put("seat",t.optString("seat",""));
                item.put("used",t.optBoolean("used") ||
                        prefs.getBoolean("used_"+eid+"_"+t.optString("id"),false));
                item.put("used_at", prefs.getString("used_time_"+eid+"_"+t.optString("id"), t.optString("used_at","")));
                item.put("reserved",t.optBoolean("reserved"));
                item.put("printed",t.optBoolean("submitted_to_printer"));
                item.put("print_known",t.has("submitted_to_printer"));
                rows.put(item);
            }catch(Exception ignored){}
        }
        return rows;
    }
    public synchronized boolean hosting(){return server!=null&&!server.isClosed();}
    private synchronized JSONObject verifyQr(String qr,String event) throws Exception {
        if(data==null)throw new Exception("Importa primero un JSON firmado");
        String[] parts=qr.split("\\.");
        if(parts.length!=3||!parts[0].equals("CE1"))throw new Exception("QR no reconocido");
        PublicKey key=KeyFactory.getInstance("EC").generatePublic(new X509EncodedKeySpec(Base64.decode(publicKey,Base64.DEFAULT)));
        Signature validator=Signature.getInstance("SHA256withECDSA");
        validator.initVerify(key);
        validator.update(parts[1].getBytes(StandardCharsets.US_ASCII));
        if(!validator.verify(decodeUrl(parts[2])))throw new Exception("QR falsificado");
        JSONObject d=new JSONObject(new String(decodeUrl(parts[1]),StandardCharsets.UTF_8));
        if(!event.equals(d.optString("e"))||!event.equals(eventId()))throw new Exception("La entrada pertenece a otra función");
        JSONObject enrolled=tickets.get(d.optString("id"));
        if(enrolled==null||enrolled.optInt("number")!=d.optInt("n"))throw new Exception("QR no incluido en el evento importado");
        if(enrolled.optBoolean("used"))throw new Exception("Entrada ya utilizada al exportar el evento");
        return d;
    }
    public synchronized JSONObject validate(String qr,String event,String device,int start,int end) {
        try {
            JSONObject d=verifyQr(qr,event);
            int number=d.optInt("n",-1);
            if(number<start||number>end)throw new Exception("Entrada fuera del rango autorizado: "+start+"–"+end);
            String used="used_"+event+"_"+d.getString("id");
            if(prefs.getBoolean(used,false))throw new Exception("Esta entrada ya fue validada aquí");
            String accessTime=new java.text.SimpleDateFormat("dd/MM/yyyy HH:mm:ss",java.util.Locale.getDefault()).format(new java.util.Date());
            if(!prefs.edit().putBoolean(used,true).putString("used_time_"+event+"_"+d.getString("id"),accessTime).commit())throw new Exception("No se pudo guardar el acceso");
            return new JSONObject().put("status","valid").put("message","ACCESO AUTORIZADO").put("number",number)
                    .put("seat",d.optString("s","")).put("device",device);
        } catch(Exception ex) {
            JSONObject error=new JSONObject();
            try{error.put("status","invalid").put("message",ex.getMessage());}catch(Exception ignored){}
            return error;
        }
    }
    public synchronized int resetLocalAccesses() throws Exception {
        if(data==null)throw new Exception("Importa primero un JSON firmado");
        String prefix="used_"+eventId()+"_", timePrefix="used_time_"+eventId()+"_";
        SharedPreferences.Editor editor=prefs.edit();
        int count=0;
        for(String key:prefs.getAll().keySet()){
            if(key.startsWith(prefix)){editor.remove(key);count++;}
            if(key.startsWith(timePrefix))editor.remove(key);
        }
        if(!editor.commit())throw new Exception("No se pudieron restablecer los accesos");
        return count;
    }
    public synchronized JSONObject accessAudit(String deviceId) throws Exception {
        if(data==null)throw new Exception("No hay un evento importado");
        String eid=eventId();
        JSONArray used=new JSONArray();
        String prefix="used_"+eid+"_";
        for(Map.Entry<String,?> item:prefs.getAll().entrySet()){
            String k=item.getKey();
            if(k.startsWith(prefix) && Boolean.TRUE.equals(item.getValue())){
                String id=k.substring(prefix.length());
                if(tickets.containsKey(id))used.put(id);
            }
        }
        return new JSONObject().put("format","CE-ACCESS-1").put("event_id",eid)
            .put("device_id",deviceId).put("ticket_ids",used)
            .put("note","Registro administrativo; cotejar con el evento original antes de fusionar");
    }
    public synchronized void startHost(String secret) throws Exception {
        if(secret==null||!secret.matches("[0-9]{6}"))throw new Exception("El PIN de coordinación debe tener 6 cifras");
        if(data==null)throw new Exception("Primero importa un JSON firmado");
        if(hosting())return;
        server=new ServerSocket(PORT);
        threads.execute(()->{
            while(hosting()) {
                try{Socket socket=server.accept(); threads.execute(()->handle(socket,secret));}
                catch(Exception e){if(hosting())try{Thread.sleep(100);}catch(InterruptedException ignored){}}
            }
        });
    }
    public synchronized void stopHost(){
        if(server!=null)try{server.close();}catch(Exception ignored){}
        server=null;
    }
    private void handle(Socket sock,String pin){
        try(Socket socket=sock){
            socket.setSoTimeout(5000);
            InputStream input=socket.getInputStream();
            ByteArrayOutputStream b=new ByteArrayOutputStream();
            byte[] suffix=new byte[4];int count=0;int ch;
            while((ch=input.read())!=-1 && b.size()<6000){
                b.write(ch);suffix[count%4]=(byte)ch;count++;
                if(count>=4 && suffix[(count-4)%4]=='\r'&&suffix[(count-3)%4]=='\n'&&suffix[(count-2)%4]=='\r'&&suffix[(count-1)%4]=='\n')break;
            }
            String head=b.toString("UTF-8");
            if(!head.startsWith("POST /validate "))throw new Exception("Método no admitido");
            int length=-1;
            for(String line:head.split("\\r?\\n")){
                if(line.toLowerCase().startsWith("content-length:"))length=Integer.parseInt(line.split(":",2)[1].trim());
            }
            if(length<1||length>100_000)throw new Exception("Longitud no permitida");
            byte[] body=new byte[length];int off=0;
            while(off<length){int n=input.read(body,off,length-off);if(n<0)throw new Exception("Solicitud incompleta");off+=n;}
            JSONObject obj=new JSONObject(new String(body,StandardCharsets.UTF_8));
            JSONObject result;
            if(!pin.equals(obj.optString("pin")))result=new JSONObject().put("status","invalid").put("message","PIN incorrecto");
            else result=validate(obj.optString("qr"),obj.optString("event_id"),obj.optString("device_id"),1,Integer.MAX_VALUE);
            byte[] payload=result.toString().getBytes(StandardCharsets.UTF_8);
            OutputStream out=socket.getOutputStream();
            out.write(("HTTP/1.1 200 OK\r\nContent-Type: application/json\r\nContent-Length: "+payload.length+"\r\nConnection: close\r\n\r\n").getBytes(StandardCharsets.US_ASCII));
            out.write(payload);out.flush();
        }catch(Exception ignored){}
    }
    public static String ips(){
        StringBuilder sb=new StringBuilder();
        try{
            Enumeration<NetworkInterface> nets=NetworkInterface.getNetworkInterfaces();
            while(nets.hasMoreElements()){
                NetworkInterface net=nets.nextElement();
                if(!net.isUp()||net.isLoopback())continue;
                Enumeration<java.net.InetAddress> addrs=net.getInetAddresses();
                while(addrs.hasMoreElements()){
                    java.net.InetAddress a=addrs.nextElement();
                    if(a instanceof Inet4Address && a.isSiteLocalAddress()){
                        if(sb.length()>0)sb.append("  ·  ");sb.append(a.getHostAddress());
                    }
                }
            }
        }catch(Exception ignored){}
        return sb.length()==0?"Sin IP local detectada":sb.toString();
    }
}
