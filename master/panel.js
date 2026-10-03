"use strict";
const $ = (selector, root=document) => root.querySelector(selector);
const $$ = (selector, root=document) => [...root.querySelectorAll(selector)];
const state = {token:sessionStorage.getItem("emby_token") || sessionStorage.getItem("token") || "", role:sessionStorage.getItem("emby_role") || sessionStorage.getItem("role") || "", data:null, view:"routes", editId:null, registering:false, loading:false, dataKey:"", navigationRole:""};
const viewNames = {routes:"线路",nodes:"节点",users:"用户",codes:"授权码",operations:"任务",settings:"公告",backups:"数据备份"};
const viewIcons = {routes:"route",nodes:"server",users:"users-round",codes:"ticket",operations:"list-checks",settings:"megaphone",backups:"database-backup"};
const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");
let themeChoice = "light";
try { themeChoice = localStorage.getItem("emby_theme") || "light"; } catch {}
if(!["light","dark","system"].includes(themeChoice))themeChoice="light";
const labels = {add:"创建",update:"更新",delete:"删除",restore:"恢复同步",pending:"等待处理",running:"处理中",succeeded:"已完成",failed:"已回退",apply:"部署",cleanup:"清理旧配置",rollback:"回退中"};
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
  "Wait for all route tasks before backup or restore":"请等待全部线路任务完成后，再备份或恢复",
  "Invalid or damaged backup":"备份文件不完整、已损坏或包含无效数据",
  "Unsupported backup format or version":"此备份格式或版本尚不受支持",
  "Backup domain does not match this panel":"备份基础域名与当前面板不同，请在相同域名的面板恢复",
  "Backup preview expired; validate again":"预览已过期，请重新选择并校验备份",
  "Panel data changed; validate backup again":"当前数据已变化，请重新选择并校验备份",
  "Preview this backup before restoring":"请先选择备份，查看恢复预览",
  "Could not save safety backup; restore cancelled":"无法保存恢复前的自动备份，已取消恢复",
  "Data restore in progress; retry shortly":"正在恢复数据，请稍后重试",
  "Active requests; retry restore shortly":"当前请求尚未结束，请稍后重试恢复",
  "Restore DNS conflict; administrator review required":"恢复的 DNS 与现有记录冲突，请管理员核对；系统将重试",
  "Request too large":"文件过大，最大支持 8 MiB",
};
const human = text => messages[text] || text;
function icons(){ $$("i[data-lucide]").forEach(icon=>icon.setAttribute("aria-hidden","true"));if(window.lucide) lucide.createIcons(); }
function element(tag, text="", cls=""){const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;}
function glyph(name){const node=element("i");node.dataset.lucide=name;node.setAttribute("aria-hidden","true");return node;}
function iconButton(icon, title, action, danger=false){const button=element("button","","icon"+(danger?" danger-icon":""));button.type="button";button.title=title;button.setAttribute("aria-label",title);const i=element("i");i.dataset.lucide=icon;button.append(i);button.addEventListener("click",action);return button;}
let toastTimer;
function toast(text,kind="success"){
  const box=$("#toast");
  $("#toast-text").textContent=text;box.dataset.kind=kind;
  box.firstElementChild.replaceWith(glyph(kind==="error"?"circle-alert":"circle-check"));
  box.hidden=false;icons();clearTimeout(toastTimer);toastTimer=setTimeout(()=>box.hidden=true,4500);
}
function applyTheme(){
  const dark=themeChoice==="dark" || (themeChoice==="system" && systemTheme.matches);
  document.documentElement.dataset.theme=dark?"dark":"light";
  $('meta[name="theme-color"]').content=dark?"#161d1b":"#f3f6f5";
  $$("[data-theme-choice]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.themeChoice===themeChoice)));
}
$$("[data-theme-choice]").forEach(button=>button.onclick=()=>{
  themeChoice=button.dataset.themeChoice;
  try{localStorage.setItem("emby_theme",themeChoice);}catch{}
  applyTheme();hideTooltip();
});
systemTheme.addEventListener("change",applyTheme);
applyTheme();
function animateView(node){
  node.getAnimations?.().forEach(animation=>animation.cancel());
  if(!reducedMotion.matches && node.animate)node.animate([{opacity:.5,transform:"translateY(3px)"},{opacity:1,transform:"translateY(0)"}],{duration:160,easing:"cubic-bezier(.2,.8,.2,1)"});
}
let tooltipTarget=null;
function hideTooltip(){
  if(tooltipTarget)tooltipTarget.removeAttribute("aria-describedby");
  tooltipTarget=null;$("#tooltip").hidden=true;
}
function showTooltip(target){
  const button=target.closest("button.icon[title]");
  if(!button || button.disabled || window.matchMedia("(hover: none)").matches)return;
  hideTooltip();tooltipTarget=button;
  const box=$("#tooltip");box.textContent=button.title;box.hidden=false;button.setAttribute("aria-describedby","tooltip");
  const rect=button.getBoundingClientRect(), tip=box.getBoundingClientRect();
  box.style.left=Math.max(8,Math.min(innerWidth-tip.width-8,rect.left+(rect.width-tip.width)/2))+"px";
  box.style.top=(rect.bottom+tip.height+12<innerHeight?rect.bottom+7:rect.top-tip.height-7)+"px";
}
document.addEventListener("pointerover",event=>showTooltip(event.target));
document.addEventListener("pointerout",event=>{if(tooltipTarget && !tooltipTarget.contains(event.relatedTarget))hideTooltip();});
document.addEventListener("focusin",event=>showTooltip(event.target));
document.addEventListener("focusout",hideTooltip);
document.addEventListener("click",hideTooltip);
document.addEventListener("scroll",hideTooltip,true);
window.addEventListener("resize",hideTooltip);
document.addEventListener("keydown",event=>{if(event.key==="Escape")hideTooltip();});
$("#toast-close").onclick=()=>{$("#toast").hidden=true;clearTimeout(toastTimer);};
function passwordVisibility(visible){
  $("#auth-password").type=visible?"text":"password";
  const button=$("#password-toggle"),title=visible?"隐藏密码":"显示密码";
  button.title=title;button.setAttribute("aria-label",title);button.setAttribute("aria-pressed",String(visible));
  button.replaceChildren(glyph(visible?"eye-off":"eye"));icons();
}
$("#password-toggle").onclick=()=>passwordVisibility($("#auth-password").type==="password");
async function api(path, method="GET", body=null){
  const token=state.token;
  const abort=new AbortController(), timer=setTimeout(()=>abort.abort(),path==="/login"?60000:20000);
  try{
    const response=await fetch("/api"+path,{method,headers:{"Content-Type":"application/json",Authorization:token},body:body===null?null:JSON.stringify(body),signal:abort.signal});
    const data=await response.json();
    if(!response.ok){if(response.status===401 && state.token===token)clearSession();throw Error(human(data.msg || "请求失败"));}
    return data;
  }catch(error){if(error.name==="AbortError")throw Error("请求超时，请刷新确认结果后再操作");throw error;}
  finally{clearTimeout(timer);}
}
async function submitting(form, work){
  const button=$('button[type="submit"]',form), error=$(".form-error",form);
  if(button.disabled)return;
  const icon=$("svg",button), original=icon?.cloneNode(true);
  button.disabled=true;button.classList.add("is-submitting");form.setAttribute("aria-busy","true");if(error)error.textContent="";
  if(form.id==="auth-form")$$("[data-auth]").forEach(tab=>tab.disabled=true);
  if(icon){icon.replaceWith(glyph("loader-circle"));icons();}
  try{await work();}catch(e){if(error)error.textContent=e.message;else toast(e.message,"error");}
  finally{button.disabled=false;button.classList.remove("is-submitting");form.removeAttribute("aria-busy");if(original)$("svg",button)?.replaceWith(original);if(form.id==="auth-form")$$("[data-auth]").forEach(tab=>tab.disabled=false);if(form.id==="restore-form")renderBackupStatus();}
}
function clearSession(){
  state.token="";state.role="";state.data=null;state.dataKey="";state.navigationRole="";state.view="routes";
  ["emby_token","emby_role","token","role"].forEach(key=>sessionStorage.removeItem(key));history.replaceState(null,"","/");
  document.body.classList.remove("workspace-mode");$("#auth").hidden=false;$("#workspace").hidden=true;$("#sidebar").hidden=true;$("#breadcrumb").hidden=true;$("#header-actions").hidden=true;
  $("#auth-form").elements.password.value="";passwordVisibility(false);
  $("#route-search").value="";$("#route-node-filter").value="";
  $$("tbody").forEach(body=>body.replaceChildren());$("#metrics").replaceChildren();$("#announcement-text").textContent="";
  $$("#workspace input,#workspace textarea").forEach(input=>{if(input.id!=="route-search" && input.type!=="number")input.value="";});
  $$("dialog[open]").forEach(d=>d.close());$("#route-form").reset();$("#node-form").reset();
  $("#node-body").replaceChildren();$("#network-nodes").replaceChildren();resetBackup();$("#saved-backup-list").replaceChildren();
  $("#toast").hidden=true;clearTimeout(toastTimer);hideTooltip();
}
async function load(silent=false){
  if(!state.token || state.loading)return;
  const token=state.token, entering=$("#workspace").hidden;
  state.loading=true;$("#refresh").disabled=true;
  if(!silent)$("#refresh").classList.add("is-loading");
  try{
    const data=await api(state.role==="admin"?"/admin/data":"/user/data");
    if(state.token!==token)return;
    state.data=data;
    document.body.classList.add("workspace-mode");
    $("#auth").hidden=true;$("#workspace").hidden=false;$("#header-actions").hidden=false;
    $("#sidebar").hidden=false;$("#breadcrumb").hidden=false;
    history.replaceState(null,"",state.role==="admin"?"/admin-panel":"/panel");
    $$("[data-panel-name]").forEach(node=>node.textContent=state.data.panel_name);document.title=state.data.panel_name;
    $("#identity").textContent=state.role==="admin"?"管理员":state.data.username;
    $("#role-label").textContent=state.role==="admin"?"管理账户":"用户账户";
    $("#avatar").textContent=state.role==="admin"?"A":state.data.username.slice(0,1).toUpperCase();
    $("#workspace-label").textContent=state.role==="admin"?"管理控制台":"用户空间";
    $("#summary").textContent=state.role==="admin"?`${state.data.users.length} 位用户 · ${state.data.routes.length} 条线路 · ${state.data.nodes.filter(n=>n.online).length}/${state.data.nodes.length} 节点在线`:`${state.data.routes.length} / ${state.data.route_limit} 条线路 · 有效期 ${state.data.expire}`;
    $("#announcement-text").textContent=state.data.announcement;$("#announcement").hidden=state.view!=="routes" || !state.data.announcement;
    $("#new-route").hidden=state.role==="admin";
    $("#route-search").placeholder=state.role==="admin"?"搜索线路、源站或用户":"搜索线路或源站";
    $("#connection-label").textContent="已连接主控";$(".connection-status").classList.remove("stale");
    const key=JSON.stringify(state.data);
    if(key!==state.dataKey){
      hideTooltip();
      $("#workspace-tag").replaceChildren(glyph(state.role==="admin"?"shield-check":"user-round"),element("span",state.role==="admin"?"管理空间":"用户空间"));
      state.dataKey=key;applyLayout();renderMetrics();renderNetwork();renderNodeFilter();renderNavigation();renderRoutes();renderNodes();renderUsers();renderCodes();renderOperations();renderBackupStatus();
      if(document.activeElement!==$('[name="text"]',$("#announcement-form"))) $('[name="text"]',$("#announcement-form")).value=state.data.announcement;
      announcementCount();icons();
    }
    $("#last-updated").textContent="更新于 "+new Date().toLocaleTimeString("zh-CN",{hour12:false});
    if(entering)animateView($("#workspace"));
  }catch(error){
    if(state.token===token){$("#connection-label").textContent="连接暂时中断";$(".connection-status").classList.add("stale");}
    throw error;
  }finally{state.loading=false;$("#refresh").disabled=false;$("#refresh").classList.remove("is-loading");}
}
function renderMetrics(){
  const data=state.data, online=data.nodes.filter(node=>node.online).length;
  const active=data.operations.filter(op=>["pending","running"].includes(op.status));
  const reserved=active.filter(op=>op.action==="add" && !data.routes.some(route=>route.subdomain===op.resource)).length;
  const entries=state.role==="admin"?[
    ["route","全部线路",data.routes.length,"条","coral"],
    ["users-round","用户总数",data.users.length,"位",""],
    ["server","在线节点",online,"/ "+data.nodes.length,"green"],
    ["activity","进行中任务",data.active_tasks ?? active.length,"项","amber"],
  ]:[
    ["route","我的线路",data.routes.length,"条","coral"],
    ["layers","可用额度",Math.max(0,data.route_limit-data.routes.length-reserved),"/ "+data.route_limit,""],
    ["server","在线节点",online,"/ "+data.nodes.length,"green"],
    ["calendar-days","账户有效期",data.expire,"","date"],
  ];
  $("#metrics").replaceChildren(...entries.map(([icon,title,value,unit,cls])=>{
    const metric=element("div","","metric "+cls),label=element("div","","metric-label"),number=element("div",String(value),"metric-value");
    label.append(glyph(icon),element("span",title));if(unit)number.append(element("span",unit,"metric-unit"));
    metric.append(label,number);return metric;
  }));
}
function renderNetwork(){
  $("#network-domain").textContent=state.data.base_domain;
  const nodes=state.data.nodes;
  $("#network-overview").classList.toggle("disconnected",!nodes.some(node=>node.online));
  $("#network-nodes").replaceChildren(...nodes.slice(0,3).map(node=>{
    const item=element("div","","network-node"+(node.online?" online":" offline")),name=element("div","","network-node-copy");
    const count=state.data.routes.filter(route=>route.node_id===node.id).length;
    name.append(element("strong",node.name),element("span",(node.online?"节点在线":"节点离线")+" · "+count+" 条线路"));
    item.append(glyph("server"),name,element("span","","signal-indicator"));return item;
  }));
  if(!nodes.length)$("#network-nodes").append(element("span","暂无节点","muted"));
  if(nodes.length>3)$("#network-nodes").append(element("span","+"+(nodes.length-3),"network-more"));
}
function renderNodeFilter(){
  const select=$("#route-node-filter"),selected=select.value;
  const all=element("option","全部节点");all.value="";
  select.replaceChildren(all,...state.data.nodes.map(node=>{const option=element("option",node.name);option.value=node.id;return option;}));
  select.value=state.data.nodes.some(node=>String(node.id)===selected)?selected:"";
}
function renderNavigation(){
  const entries=state.role==="admin"?[["routes","线路"],["nodes","节点"],["users","用户"],["codes","授权码"],["operations","任务"],["settings","公告"],["backups","数据备份"]]:[["routes","线路"],["operations","任务"]];
  if(!entries.some(([key])=>key===state.view))state.view="routes";
  const nav=$("#navigation");
  if(state.navigationRole!==state.role){
    state.navigationRole=state.role;nav.setAttribute("role","tablist");
    nav.replaceChildren(...entries.map(([key,title])=>{
      const button=element("button");button.type="button";button.dataset.view=key;button.id="nav-"+key;
      button.setAttribute("role","tab");button.setAttribute("aria-label",title);button.setAttribute("aria-controls",key+"-view");
      button.append(glyph(viewIcons[key]),element("span",title),element("span","","nav-count"));$(".nav-count",button).setAttribute("aria-hidden","true");
      button.onclick=()=>{if(state.view===key)return;state.view=key;renderNavigation();animateView($("#"+key+"-view"));hideTooltip();if(window.matchMedia("(max-width:760px)").matches)button.scrollIntoView({block:"nearest",inline:"nearest",behavior:reducedMotion.matches?"instant":"smooth"});if(key==="backups")loadSavedBackups().catch(e=>toast(e.message,"error"));};
      return button;
    }));
  }
  $$("button",nav).forEach(button=>{
    const key=button.dataset.view,selected=state.view===key;
    button.setAttribute("aria-selected",String(selected));button.tabIndex=selected?0:-1;
    $(".nav-count",button).textContent=["settings","backups"].includes(key)?"":state.data[key]?.length || 0;
  });
  $$(".view").forEach(view=>view.hidden=view.id!==state.view+"-view");
  $("#network-overview").hidden=!["routes","nodes"].includes(state.view);
  $("#metrics").hidden=state.view!=="routes";
  $("#announcement").hidden=state.view!=="routes" || !state.data.announcement;
  const heading=state.view==="routes"?(state.role==="admin"?"线路管理":"我的线路"):({nodes:"节点管理",users:"用户管理",codes:"授权码",operations:"线路任务",settings:"公告管理",backups:"数据备份"}[state.view]);
  $("#heading").textContent=heading;$("#current-view").textContent=viewNames[state.view];
  $("#routes-heading").textContent=state.role==="admin"?"全部线路":"线路入口";
  $$(".view").forEach(view=>{view.setAttribute("role","tabpanel");view.setAttribute("aria-labelledby","nav-"+view.id.replace("-view",""));});
  icons();
}
$("#navigation").addEventListener("keydown",event=>{
  if(!["ArrowRight","ArrowDown","ArrowLeft","ArrowUp","Home","End"].includes(event.key))return;
  event.preventDefault();const buttons=$$("button",$("#navigation")),index=buttons.indexOf(document.activeElement);
  const next=event.key==="Home"?0:event.key==="End"?buttons.length-1:(index+(["ArrowRight","ArrowDown"].includes(event.key)?1:-1)+buttons.length)%buttons.length;
  buttons[next].click();buttons[next].focus();
});
$$("[data-auth]").forEach(button=>button.addEventListener("keydown",event=>{
  if(!["ArrowRight","ArrowLeft","Home","End"].includes(event.key))return;
  event.preventDefault();const buttons=$$("[data-auth]");
  const next=event.key==="Home"?buttons[0]:event.key==="End"?buttons[1]:buttons.find(node=>node!==button);
  next.click();next.focus();
}));
function cell(row,text,cls="",label=""){const td=element("td",String(text??""),cls);if(label)td.dataset.label=label;row.append(td);return td;}
function status(value){return element("span",labels[value] || (value==="online"?"在线":"离线"),"badge "+value);}
function renderRoutes(){
  const admin=state.role==="admin", query=$("#route-search").value.trim().toLowerCase(), node=$("#route-node-filter").value;
  const head=element("tr");["线路",...(admin?["用户"]:[]),"节点","源站","操作"].forEach(title=>head.append(element("th",title)));$("#route-head").replaceChildren(head);
  const rows=state.data.routes.filter(r=>(!node || String(r.node_id)===node) && [r.subdomain,r.target,r.user,r.node_name].some(v=>String(v||"").toLowerCase().includes(query)));
  $("#route-count").textContent=(query || node)?rows.length+" / "+state.data.routes.length:rows.length;
  $("#route-body").replaceChildren(...rows.map(route=>{
    const row=element("tr"), first=cell(row,""),name=element("div","","route-name mono");
    name.append(glyph("route"),element("span",route.subdomain));first.append(name);
    const url=`https://${route.subdomain}.${state.data.base_domain}:${route.node_port}`;
    const entry=element("a","","cell-sub route-entry");entry.href=url;entry.target="_blank";entry.rel="noopener noreferrer";entry.title="打开线路入口";entry.setAttribute("aria-label","打开 "+route.subdomain+" 线路入口");entry.setAttribute("translate","no");entry.append(element("span",url),glyph("arrow-up-right"));first.append(entry);
    if(admin){const user=element("div","","user-cell");user.append(element("span",String(route.user || "").slice(0,1).toUpperCase(),"avatar"),element("span",route.user));cell(row,"","","用户").append(user);}
    const nodeName=element("div","","node-name");nodeName.append(glyph("server"),element("span",route.node_name || "节点缺失"));cell(row,"","","节点").append(nodeName);
    cell(row,route.target,"mono","源站");
    const actions=element("div","","actions");
    actions.append(iconButton("copy","复制入口",()=>copy(url)),iconButton("pencil","修改线路",()=>openRoute(route)),iconButton("trash-2","删除线路",()=>confirmDelete("删除线路",route.subdomain,async()=>{await api(admin?"/admin/delete_route":"/user/delete_route","POST",{id:route.id});toast("删除任务已提交");await load();}),true));
    const pending=state.data.operations.some(o=>o.resource===route.subdomain && ["pending","running"].includes(o.status));
    const online=state.data.nodes.find(node=>node.id===route.node_id)?.online;
    const signal=element("span","","route-signal "+(pending?"pending":online?"online":"offline"));signal.title=pending?"配置同步中":online?"节点在线":"节点离线";signal.setAttribute("aria-label",signal.title);name.append(signal);
    if(pending)$$("button",actions).slice(1).forEach(b=>b.disabled=true);
    cell(row,"","action-cell").append(actions);return row;
  }));
  $("#route-empty p").textContent=(query || node)?"没有匹配的线路":"暂无线路";$("#route-empty").hidden=rows.length>0;
  $(".empty-actions",$("#route-empty"))?.remove();
  if(!rows.length){
    const actions=element("div","","empty-actions");
    if(query || node){const reset=element("button","清除筛选");reset.type="button";reset.onclick=()=>{$("#route-search").value="";$("#route-node-filter").value="";renderRoutes();icons();};actions.append(reset);}
    else if(!admin){const add=element("button");add.type="button";add.append(glyph("plus"),element("span","新建线路"));add.onclick=()=>openRoute();actions.append(add);}
    if(actions.children.length)$("#route-empty").append(actions);
  }
}
function renderNodes(){
  if(state.role!=="admin")return;
  $("#node-count").textContent=state.data.nodes.length;
  $("#node-body").replaceChildren(...state.data.nodes.map(node=>{
    const item=element("article","","node-tile"+(node.online?" online":" offline")),head=element("div","","node-tile-heading"),emblem=element("span","","node-tile-emblem");emblem.append(glyph("server"));
    head.append(emblem,status(node.online?"online":"offline"));
    const ports=element("dl","","node-ports");
    for(const [title,value] of [["通信地址",`${node.host}:${node.port}`],["公网端口",node.public_port || node.port],["关联线路",state.data.routes.filter(route=>route.node_id===node.id).length]]){ports.append(element("dt",title),element("dd",String(value),"mono"));}
    const footer=element("div","","node-tile-footer");footer.append(element("span","节点 #"+node.id),iconButton("trash-2","删除节点",()=>confirmDelete("删除节点",node.name,async()=>{await api("/admin/delete_node","POST",{id:node.id});await load();}),true));
    item.append(head,element("h3",node.name),ports,footer);return item;
  }));$("#node-empty").hidden=state.data.nodes.length>0;
}
function renderUsers(){
  if(state.role!=="admin")return;
  $("#user-count").textContent=state.data.users.length;
  $("#user-body").replaceChildren(...state.data.users.map(user=>{const row=element("tr"),identity=element("div","","user-cell");identity.append(element("span",user.username.slice(0,1).toUpperCase(),"avatar"),element("strong",user.username));cell(row,"").append(identity);cell(row,user.expire,"","有效期");cell(row,user.route_count,"","线路数");const input=element("input","","quota-input");input.type="number";input.min="0";input.max="1000";input.value=user.route_limit;input.setAttribute("aria-label",user.username+" 线路额度");cell(row,"","","额度").append(input);cell(row,"","action-cell").append(iconButton("save","保存额度",async event=>{const button=event.currentTarget;if(button.disabled)return;button.disabled=true;try{await api("/admin/update_user_limit","POST",{username:user.username,route_limit:input.value});toast("额度已保存");await load();}catch(e){toast(e.message,"error");}finally{button.disabled=false;}}));return row;}));$("#user-empty").hidden=state.data.users.length>0;
}
function renderCodes(){
  if(state.role!=="admin")return;
  $("#code-count").textContent=state.data.codes.length;
  $("#code-body").replaceChildren(...state.data.codes.map(code=>{const row=element("tr");cell(row,code.code,"mono");cell(row,code.dur,"","额度");cell(row,"","","状态").append(element("span",code.used?"已使用":"未使用","badge "+(code.used?"used":"available")));cell(row,code.user || "—","","用户");cell(row,"","action-cell").append(iconButton("copy","复制授权码",()=>copy(code.code)));return row;}));$("#code-empty").hidden=state.data.codes.length>0;
}
function renderOperations(){
  $("#operation-count").textContent=state.data.operations.length;
  $("#operation-body").replaceChildren(...state.data.operations.map(op=>{const row=element("tr");cell(row,op.resource,"mono");cell(row,labels[op.action],"","操作");cell(row,"","","状态").append(status(op.status));cell(row,labels[op.phase],"","阶段");cell(row,human(op.error) || "—","","详情");return row;}));$("#operation-empty").hidden=state.data.operations.length>0;
}
let selectedBackup=null, backupConfirmation=null, backupSequence=0, backupWorking=false;
const backupTableNames={users:"用户",routes:"线路",nodes:"节点",auth_codes:"授权码",settings:"公告与设置"};
function resetBackup(){
  backupSequence++;selectedBackup=null;backupConfirmation=null;
  $("#backup-file").value="";$("#backup-preview").hidden=true;$("#backup-preview-body").replaceChildren();
  $("#restore-form").reset();$("#restore-backup").disabled=true;$("#backup-error").textContent="";
}
function renderBackupStatus(){
  if(state.role!=="admin")return;
  const busy=(state.data.active_tasks || 0)>0;
  $("#backup-busy").hidden=!busy;
  $("#export-backup").disabled=busy || backupWorking;$("#choose-backup").disabled=busy || backupWorking;
  $("#restore-backup").disabled=busy || backupWorking || !selectedBackup || !$("#restore-form").elements.confirm.checked;
  const counts=[["users-round",state.data.users.length,"用户"],["route",state.data.routes.length,"线路"],["server",state.data.nodes.length,"节点"]];
  $("#backup-current-counts").replaceChildren(...counts.map(([icon,count,title])=>{const node=element("span");node.append(glyph(icon),element("strong",String(count)),element("span",title));return node;}));
}
async function backupFetch(path){
  const token=state.token,abort=new AbortController(),timer=setTimeout(()=>abort.abort(),30000);
  try{
    const response=await fetch("/api"+path,{headers:{Authorization:token},signal:abort.signal});
    if(!response.ok){let body={};try{body=await response.json();}catch{}if(response.status===401 && state.token===token)clearSession();throw Error(human(body.msg || "备份请求失败"));}
    if(state.token!==token)throw Error("登录状态已变化");return response;
  }finally{clearTimeout(timer);}
}
async function downloadBackup(path,name){
  const response=await backupFetch(path),blob=await response.blob();
  const link=element("a"),url=URL.createObjectURL(blob);
  link.href=url;link.download=name;document.body.append(link);link.click();link.remove();setTimeout(()=>URL.revokeObjectURL(url),30000);
}
async function prepareBackup(backup,name){
  resetBackup();const sequence=backupSequence,token=state.token;
  backupWorking=true;renderBackupStatus();$("#restore-result").hidden=true;$("#backup-error").textContent="正在校验备份…";
  try{
    const result=await api("/admin/backups/preview","POST",{backup});
    if(sequence!==backupSequence || token!==state.token)return;
    selectedBackup=backup;backupConfirmation=result.confirmation;
    $("#backup-filename").textContent=name;
    $("#backup-date").textContent=new Date(result.created_at).toLocaleString("zh-CN")+" · "+result.base_domain;
    $("#backup-preview-body").replaceChildren(...Object.entries(result.counts).map(([table,counts])=>{
      const row=element("tr");cell(row,backupTableNames[table]);for(const [key,label] of [["current","当前"],["incoming","恢复后"],["added","新增"],["updated","更新"],["removed","移除"]])cell(row,counts[key],key==="removed" && counts[key]?"destructive-text":"",label);return row;
    }));
    $("#backup-preview").hidden=false;$("#backup-error").textContent="";animateView($("#backup-preview"));
  }catch(error){if(sequence===backupSequence)$("#backup-error").textContent=error.message;}
  finally{backupWorking=false;renderBackupStatus();icons();}
}
async function loadSavedBackups(){
  if(state.role!=="admin")return;
  const token=state.token,result=await api("/admin/backups/list");if(token!==state.token)return;
  $("#saved-backup-count").textContent=result.backups.length;$("#saved-backup-empty").hidden=result.backups.length>0;
  $("#saved-backup-list").replaceChildren(...result.backups.map(backup=>{
    const item=element("div","","saved-backup-row"),info=element("div","","saved-backup-info"),actions=element("div","","actions"),name=element("div");
    name.append(element("strong",new Date(backup.created_at*1000).toLocaleString("zh-CN")),element("p",(backup.size/1024).toFixed(1)+" KiB · 恢复前自动保存","muted"));info.append(glyph("archive"),name);
    actions.append(iconButton("download","下载自动备份",()=>downloadBackup("/admin/backups/saved/"+backup.name,backup.name).catch(e=>toast(e.message,"error"))),iconButton("archive-restore","选择此备份恢复",async()=>{if(backupWorking)return;try{const response=await backupFetch("/admin/backups/saved/"+backup.name);await prepareBackup(await response.json(),backup.name);}catch(e){toast(e.message,"error");}}));
    item.append(info,actions);return item;
  }));icons();
}
$("#choose-backup").onclick=()=>$("#backup-file").click();
$("#backup-file").onchange=async event=>{
  const file=event.target.files[0];if(!file)return;
  if(file.size>8*1024*1024){resetBackup();$("#backup-error").textContent="文件过大，最大支持 8 MiB";return;}
  try{await prepareBackup(JSON.parse(await file.text()),file.name);}catch{resetBackup();$("#backup-error").textContent="无法读取备份，请选择有效的 JSON 文件";}
};
$("#cancel-backup").onclick=resetBackup;
$("#restore-form").elements.confirm.onchange=renderBackupStatus;
$("#export-backup").onclick=async()=>{
  if(backupWorking)return;backupWorking=true;renderBackupStatus();
  try{await downloadBackup("/admin/backups/export","emby-edge-"+new Date().toISOString().replace(/[:.]/g,"-")+".json");toast("备份已导出");}catch(e){toast(e.message,"error");}finally{backupWorking=false;renderBackupStatus();}
};
$("#refresh-backups").onclick=()=>loadSavedBackups().catch(e=>toast(e.message,"error"));
$("#restore-form").onsubmit=event=>{
  event.preventDefault();if(!selectedBackup || !backupConfirmation || backupWorking || !event.target.elements.confirm.checked)return;
  submitting(event.target,async()=>{
    backupWorking=true;renderBackupStatus();
    try{
      const result=await api("/admin/backups/restore","POST",{backup:selectedBackup,confirmation:backupConfirmation});
      resetBackup();$("#restore-result").textContent="数据已恢复。"+(result.tasks?result.tasks+" 条线路正在同步，可在任务中查看进度。":"")+"恢复前的自动备份已保留。";$("#restore-result").hidden=false;
      toast("数据已恢复，自动备份已保留");await load();await loadSavedBackups();
    }catch(error){resetBackup();$("#backup-error").textContent=error.message;}
    finally{backupWorking=false;renderBackupStatus();}
  });
};
let routeLayout="auto";
try{routeLayout=localStorage.getItem("emby_route_layout") || "auto";}catch{}
function applyLayout(){const layout=["table","grid"].includes(routeLayout)?routeLayout:state.role==="admin"?"table":"grid";$("#routes-view").dataset.layout=layout;$$("[data-layout]").forEach(button=>button.setAttribute("aria-pressed",String(button.dataset.layout===layout)));}
$$("[data-layout]").forEach(button=>button.onclick=()=>{routeLayout=button.dataset.layout;try{localStorage.setItem("emby_route_layout",routeLayout);}catch{}applyLayout();animateView($("#route-body"));});
applyLayout();
async function copy(value){
  try{await navigator.clipboard.writeText(value);toast("已复制");}
  catch{const buffer=element("textarea","","clipboard-buffer");buffer.value=value;document.body.append(buffer);buffer.select();try{if(!document.execCommand("copy"))throw Error();toast("已复制");}catch{toast("复制不可用，请手动选择入口地址");}finally{buffer.remove();}}
}
function openRoute(route=null){
  const form=$("#route-form");form.reset();$(".form-error",form).textContent="";state.editId=route?.id??null;
  $("#route-title").textContent=route?"修改线路":"新建线路";$("#suffix-label").hidden=!!route;
  $("#route-submit-label").textContent=route?"保存更改":"创建线路";
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
$$("[data-auth]").forEach(button=>button.onclick=()=>{state.registering=button.dataset.auth==="register";$$("[data-auth]").forEach(b=>{b.setAttribute("aria-selected",String(b===button));b.tabIndex=b===button?0:-1;});$("#code-label").hidden=!state.registering;$("#auth-form").elements.code.required=state.registering;$("#auth-form").elements.password.autocomplete=state.registering?"new-password":"current-password";$("#auth-submit").textContent=state.registering?"注册":"登录";$("#auth-caption").textContent=state.registering?"创建账户":"账户登录";$("#auth-error").textContent="";});
$("#auth-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{try{const body=Object.fromEntries(new FormData(event.target));if(!state.registering)body.code="";const result=await api("/login","POST",body);state.token=result.token;state.role=result.role;state.view="routes";state.dataKey="";state.navigationRole="";sessionStorage.setItem("emby_token",state.token);sessionStorage.setItem("emby_role",state.role);sessionStorage.setItem("token",state.token);sessionStorage.setItem("role",state.role);event.target.elements.password.value="";passwordVisibility(false);$("#auth-error").textContent="";await load();}catch(e){$("#auth-error").textContent=e.message;}});};
$("#refresh").onclick=()=>load().catch(e=>toast(e.message,"error"));
$("#logout").onclick=async()=>{try{await api("/logout","POST",{});}catch{}clearSession();};
$("#route-search").oninput=()=>{if(state.data){renderRoutes();icons();}};
$("#route-node-filter").onchange=()=>{if(state.data){renderRoutes();icons();}};
$("#new-route").onclick=()=>openRoute();
$("#route-form").elements.subdomain.oninput=preview;
$("#route-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{const data=Object.fromEntries(new FormData(event.target));let path="/user/add_route";if(state.editId!==null){data.id=state.editId;path=state.role==="admin"?"/admin/update_route":"/user/update_route";}await api(path,"POST",data);$("#route-dialog").close();toast("线路任务已提交");await load();});};
$("#new-node").onclick=()=>{$("#node-form").reset();$(".form-error",$("#node-form")).textContent="";$("#node-dialog").showModal();};
$("#node-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{await api("/admin/add_node","POST",Object.fromEntries(new FormData(event.target)));$("#node-dialog").close();event.target.elements.key.value="";toast("节点已添加，等待健康检查");await load();});};
$("#code-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{await api("/admin/generate","POST",Object.fromEntries(new FormData(event.target)));toast("授权码已签发");await load();});};
$("#announcement-form").onsubmit=event=>{event.preventDefault();submitting(event.target,async()=>{await api("/admin/update_announcement","POST",Object.fromEntries(new FormData(event.target)));toast("公告已发布");await load();});};
function announcementCount(){$("#announcement-count").textContent=$('[name="text"]',$("#announcement-form")).value.length+" / 10000";}
$('[name="text"]',$("#announcement-form")).oninput=announcementCount;
$("#confirm-yes").onclick=async()=>{const button=$("#confirm-yes");if(button.disabled)return;button.disabled=true;try{await confirmAction?.();$("#confirm-dialog").close();}catch(e){toast(e.message,"error");}finally{button.disabled=false;}};
setInterval(()=>{if(state.token && !document.hidden && !document.activeElement?.matches("input,textarea,select") && !document.querySelector("dialog[open]"))load(true).catch(()=>{});},5000);
document.addEventListener("visibilitychange",()=>{if(document.hidden)passwordVisibility(false);});
$$("[data-auth]").forEach(button=>button.tabIndex=button.getAttribute("aria-selected")==="true"?0:-1);
icons();if(state.token)load().catch(e=>toast(e.message,"error"));
