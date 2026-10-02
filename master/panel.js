"use strict";
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const state = {token:sessionStorage.getItem("emby_token") || sessionStorage.getItem("token") || "", role:sessionStorage.getItem("emby_role") || sessionStorage.getItem("role") || "", data:null, view:"routes", editId:null, registering:false, loading:false};
const labels = {add:"创建",update:"更新",delete:"删除",pending:"等待处理",running:"处理中",succeeded:"已完成",failed:"已回退",apply:"部署",cleanup:"清理旧配置",rollback:"回退中"};
const messages = {
  "Session expired":"会话已过期，请重新登录", "Invalid username or password":"用户名或密码错误",
  "Authorization code is invalid or already used":"授权码无效或已使用", "Username already exists":"用户名已存在",
  "Username is reserved":"此用户名已保留", "Route quota reached":"线路额度已用完", "Node is offline":"目标节点离线",
  "Route prefix already exists":"线路前缀已存在", "This route already has an active operation":"该线路已有进行中的任务",
  "Origin must use a public HTTP(S) address":"源站必须使用有效的公网 HTTP(S) 地址", "Invalid origin URL":"源站地址格式无效",
  "Too many login attempts; retry in 15 minutes":"登录尝试过于频繁，请 15 分钟后重试",
  "Migrate all routes before deleting this node":"请先迁移此节点上的全部线路", "Node has unfinished operations":"节点还有未完成的任务",
  "Node endpoint already exists":"该节点通信地址已存在", "Password is required":"请输入密码",
  "Username must contain 2-24 letters or digits":"用户名仅支持 2-24 位英文字母和数字",
  "Invalid route prefix":"线路缩写仅支持小写字母、数字和连字符",
  "DNS name already exists; choose another route prefix":"此 DNS 名称已有记录，请更换线路缩写",
  "DNS record differs from managed route; administrator review required":"DNS 记录与线路不一致，请联系管理员核对",
  "Upstream unavailable or invalid response":"上游暂不可用，系统将自动重试",
  "Cloudflare DNS lookup rejected":"DNS 查询失败，系统将自动重试",
  "Cloudflare DNS update rejected":"DNS 更新失败，系统将自动重试",
  "Cloudflare DNS deletion rejected":"DNS 删除失败，系统将自动重试",
  "Cloudflare DNS restore rejected":"DNS 回退失败，系统将自动重试",
  "Worker rejected operation":"节点拒绝了操作，请联系管理员检查",
  "Database temporarily busy; retry shortly":"数据库暂忙，请稍后重试",
  "Internal error; check master logs":"系统内部错误，请联系管理员查看日志",
  "Account expired":"账户已过期", "Node not found":"节点不存在",
  "Expected an integer":"请输入整数", "Value out of range":"数值超出允许范围",
};
const human = text => messages[text] || text;
function icons(){ if(window.lucide) lucide.createIcons(); }
function element(tag, text="", cls=""){const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;}
function iconButton(icon, title, action, danger=false){const button=element("button","","icon"+(danger?" danger-icon":""));button.type="button";button.title=title;button.setAttribute("aria-label",title);const i=element("i");i.dataset.lucide=icon;button.append(i);button.addEventListener("click",action);return button;}
let toastTimer;
function toast(text){$("#toast").textContent=text;$("#toast").hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$("#toast").hidden=true,4500);}
async function api(path, method="GET", body=null){
  const abort=new AbortController(), timer=setTimeout(()=>abort.abort(),path==="/login"?60000:20000);
  try{
    const response=await fetch("/api"+path,{method,headers:{"Content-Type":"application/json",Authorization:state.token},body:body===null?null:JSON.stringify(body),signal:abort.signal});
    const data=await response.json();
    if(!response.ok){if(response.status===401)clearSession();throw Error(human(data.msg || "请求失败"));}
    return data;
  }catch(error){if(error.name==="AbortError")throw Error("请求超时，请刷新确认结果后再操作");throw error;}
  finally{clearTimeout(timer);}
}
async function submitting(form, work){
  const button=$('button[type="submit"]',form), error=$(".form-error",form);
  button.disabled=true;if(error)error.textContent="";
  try{await work();}catch(e){if(error)error.textContent=e.message;else toast(e.message);}finally{button.disabled=false;}
}
function clearSession(){state.token="";state.role="";state.data=null;["emby_token","emby_role","token","role"].forEach(key=>sessionStorage.removeItem(key));history.replaceState(null,"","/");$("#auth").hidden=false;$("#workspace").hidden=true;$("#header-actions").hidden=true;$$("dialog[open]").forEach(d=>d.close());}
async function load(){
  if(!state.token || state.loading)return;
  state.loading=true;$("#refresh").disabled=true;
  try{
    state.data=await api(state.role==="admin"?"/admin/data":"/user/data");
    $("#auth").hidden=true;$("#workspace").hidden=false;$("#header-actions").hidden=false;
    history.replaceState(null,"",state.role==="admin"?"/admin-panel":"/panel");
    $("#brand").textContent=state.data.panel_name;document.title=state.data.panel_name;
    $("#identity").textContent=state.role==="admin"?"管理员":state.data.username;
    $("#heading").textContent=state.role==="admin"?"管理控制台":"我的线路";
    $("#summary").textContent=state.role==="admin"?`${state.data.users.length} 位用户 · ${state.data.routes.length} 条线路 · ${state.data.nodes.filter(n=>n.online).length}/${state.data.nodes.length} 节点在线`:`${state.data.routes.length} / ${state.data.route_limit} 条线路 · 有效期 ${state.data.expire}`;
    $("#announcement").textContent=state.data.announcement;$("#announcement").hidden=!state.data.announcement;
    $("#new-route").hidden=state.role==="admin";renderNavigation();renderRoutes();renderNodes();renderUsers();renderCodes();renderOperations();
    if(document.activeElement!==$('[name="text"]',$("#announcement-form"))) $('[name="text"]',$("#announcement-form")).value=state.data.announcement;
    icons();
  }finally{state.loading=false;$("#refresh").disabled=false;}
}
function renderNavigation(){
  const entries=state.role==="admin"?[["routes","线路"],["nodes","节点"],["users","用户"],["codes","授权码"],["operations","任务"],["settings","公告"]]:[["routes","线路"],["operations","任务"]];
  $("#navigation").replaceChildren(...entries.map(([key,title])=>{const b=element("button",title);b.type="button";b.setAttribute("aria-selected",String(state.view===key));b.onclick=()=>{state.view=key;renderNavigation();};return b;}));
  $$(".view").forEach(view=>view.hidden=view.id!==state.view+"-view");
}
function cell(row,text,cls=""){const td=element("td",String(text??""),cls);row.append(td);return td;}
function status(value){return element("span",labels[value] || (value==="online"?"在线":"离线"),"badge "+value);}
function renderRoutes(){
  const admin=state.role==="admin", query=$("#route-search").value.trim().toLowerCase();
  const head=element("tr");["线路",...(admin?["用户"]:[]),"节点","源站","操作"].forEach(title=>head.append(element("th",title)));$("#route-head").replaceChildren(head);
  const rows=state.data.routes.filter(r=>[r.subdomain,r.target,r.user,r.node_name].some(v=>String(v||"").toLowerCase().includes(query)));
  $("#route-body").replaceChildren(...rows.map(route=>{
    const row=element("tr"), first=cell(row,route.subdomain,"mono");
    const url=`https://${route.subdomain}.${state.data.base_domain}:${route.node_port}`;
    first.append(element("div",url,"cell-sub mono"));if(admin)cell(row,route.user).dataset.label="用户";cell(row,route.node_name || "节点缺失").dataset.label="节点";cell(row,route.target,"mono").dataset.label="源站";
    const actions=element("div","","actions");
    actions.append(iconButton("copy","复制入口",()=>copy(url)),iconButton("pencil","修改线路",()=>openRoute(route)),iconButton("trash-2","删除线路",()=>confirmDelete("删除线路",route.subdomain,async()=>{await api(admin?"/admin/delete_route":"/user/delete_route","POST",{id:route.id});toast("删除任务已提交");await load();}),true));
    const pending=state.data.operations.some(o=>o.resource===route.subdomain && ["pending","running"].includes(o.status));
    if(pending)$$("button",actions).slice(1).forEach(b=>b.disabled=true);
    cell(row,"").append(actions);return row;
  }));$("#route-empty").textContent=query?"没有匹配的线路":"暂无线路";$("#route-empty").hidden=rows.length>0;
}
function renderNodes(){
  if(state.role!=="admin")return;
  $("#node-body").replaceChildren(...state.data.nodes.map(node=>{const row=element("tr");cell(row,node.name);cell(row,`${node.host}:${node.port}`,"mono");cell(row,node.public_port || node.port);cell(row,"").append(status(node.online?"online":"offline"));cell(row,"").append(iconButton("trash-2","删除节点",()=>confirmDelete("删除节点",node.name,async()=>{await api("/admin/delete_node","POST",{id:node.id});await load();}),true));return row;}));$("#node-empty").hidden=state.data.nodes.length>0;
}
function renderUsers(){
  if(state.role!=="admin")return;
  $("#user-body").replaceChildren(...state.data.users.map(user=>{const row=element("tr");cell(row,user.username);cell(row,user.expire);cell(row,user.route_count);const input=element("input","","quota-input");input.type="number";input.min="0";input.max="1000";input.value=user.route_limit;input.setAttribute("aria-label",user.username+" 线路额度");cell(row,"").append(input);cell(row,"").append(iconButton("save","保存额度",async()=>{try{await api("/admin/update_user_limit","POST",{username:user.username,route_limit:input.value});toast("额度已保存");await load();}catch(e){toast(e.message);}}));return row;}));$("#user-empty").hidden=state.data.users.length>0;
}
function renderCodes(){
  if(state.role!=="admin")return;
  $("#code-body").replaceChildren(...state.data.codes.map(code=>{const row=element("tr");cell(row,code.code,"mono");cell(row,code.dur);cell(row,code.used?"已使用":"未使用");cell(row,code.user || "—");cell(row,"").append(iconButton("copy","复制授权码",()=>copy(code.code)));return row;}));$("#code-empty").hidden=state.data.codes.length>0;
}
function renderOperations(){
  $("#operation-body").replaceChildren(...state.data.operations.map(op=>{const row=element("tr");cell(row,op.resource,"mono");cell(row,labels[op.action]);cell(row,"").append(status(op.status));cell(row,labels[op.phase]);cell(row,human(op.error) || "—");return row;}));$("#operation-empty").hidden=state.data.operations.length>0;
}
async function copy(value){
  try{await navigator.clipboard.writeText(value);toast("已复制");}
  catch{const buffer=element("textarea","","clipboard-buffer");buffer.value=value;document.body.append(buffer);buffer.select();try{if(!document.execCommand("copy"))throw Error();toast("已复制");}catch{toast("复制不可用，请手动选择入口地址");}finally{buffer.remove();}}
}
function openRoute(route=null){
  const form=$("#route-form");form.reset();$(".form-error",form).textContent="";state.editId=route?.id??null;
  $("#route-title").textContent=route?"修改线路":"新建线路";$("#suffix-label").hidden=!!route;
  form.elements.subdomain.required=!route;
  form.elements.node_id.replaceChildren(...state.data.nodes.map(node=>{const option=element("option",node.name+(node.online?"":" · 离线"));option.value=node.id;option.disabled=!node.online && node.id!==route?.node_id;return option;}));
  if(route){form.elements.node_id.value=route.node_id;form.elements.target.value=route.target;$("#route-preview").textContent=route.subdomain+"."+state.data.base_domain;}
  else{const available=state.data.nodes.find(n=>n.online);if(available)form.elements.node_id.value=available.id;preview();}
  $("#route-dialog").showModal();
}
function preview(){if(state.editId!==null)return;$("#route-preview").textContent=(state.data?.username?.toLowerCase() || "")+"-"+$("#route-form").elements.subdomain.value+"."+state.data?.base_domain;}
let confirmAction=null;
function confirmDelete(title,text,action){$("#confirm-title").textContent=title;$("#confirm-text").textContent=text;confirmAction=action;$("#confirm-dialog").showModal();}
$$(".close").forEach(button=>button.onclick=()=>button.closest("dialog").close());
$$("[data-auth]").forEach(button=>button.onclick=()=>{state.registering=button.dataset.auth==="register";$$("[data-auth]").forEach(b=>b.setAttribute("aria-selected",String(b===button)));$("#code-label").hidden=!state.registering;$("#auth-form").elements.code.required=state.registering;$("#auth-form").elements.password.autocomplete=state.registering?"new-password":"current-password";$("#auth-submit").textContent=state.registering?"注册":"登录";$("#auth-error").textContent="";});
$("#auth-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{try{const body=Object.fromEntries(new FormData(event.target));if(!state.registering)body.code="";const result=await api("/login","POST",body);state.token=result.token;state.role=result.role;state.view="routes";sessionStorage.setItem("emby_token",state.token);sessionStorage.setItem("emby_role",state.role);sessionStorage.setItem("token",state.token);sessionStorage.setItem("role",state.role);event.target.elements.password.value="";$("#auth-error").textContent="";await load();}catch(e){$("#auth-error").textContent=e.message;}});};
$("#refresh").onclick=()=>load().catch(e=>toast(e.message));
$("#logout").onclick=async()=>{try{await api("/logout","POST",{});}catch{}clearSession();};
$("#route-search").oninput=()=>{if(state.data){renderRoutes();icons();}};
$("#new-route").onclick=()=>openRoute();
$("#route-form").elements.subdomain.oninput=preview;
$("#route-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{const data=Object.fromEntries(new FormData(event.target));let path="/user/add_route";if(state.editId!==null){data.id=state.editId;path=state.role==="admin"?"/admin/update_route":"/user/update_route";}await api(path,"POST",data);$("#route-dialog").close();toast("线路任务已提交");await load();});};
$("#new-node").onclick=()=>{$("#node-form").reset();$(".form-error",$("#node-form")).textContent="";$("#node-dialog").showModal();};
$("#node-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{await api("/admin/add_node","POST",Object.fromEntries(new FormData(event.target)));$("#node-dialog").close();event.target.elements.key.value="";toast("节点已添加，等待健康检查");await load();});};
$("#code-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{await api("/admin/generate","POST",Object.fromEntries(new FormData(event.target)));toast("授权码已签发");await load();});};
$("#announcement-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{await api("/admin/update_announcement","POST",Object.fromEntries(new FormData(event.target)));toast("公告已发布");await load();});};
$("#confirm-yes").onclick=async()=>{const button=$("#confirm-yes");button.disabled=true;try{await confirmAction?.();$("#confirm-dialog").close();}catch(e){toast(e.message);}finally{button.disabled=false;}};
setInterval(()=>{if(state.token && !document.hidden && !document.activeElement?.matches("input,textarea,select") && !document.querySelector("dialog[open]"))load().catch(()=>{});},5000);
icons();if(state.token)load().catch(e=>toast(e.message));
