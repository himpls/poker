const $ = s => document.querySelector(s);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const W = window.Telegram?.WebApp;
const S = {tab:'home',clubId:null,clubs:[],club:null,members:[],games:[],stats:null,game:null,period:'all',page:0};
const statusNames = {planned:'Запланирована',active:'За столом',reconciling:'Сверка результатов',completed:'Завершена',cancelled:'Отменена'};
const roleNames = {owner:'Владелец',organizer:'Организатор',member:'Участник'};
const opNames = {buyin:'Первый вход',rebuy:'Докупка',cashout:'Кэшаут'};
const icons = {
 home:'<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-8H9v8H4a1 1 0 0 1-1-1Z"/>',
 games:'<rect x="3" y="5" width="18" height="14" rx="5"/><path d="M8 3v4m8-4v4M8 17v4m8-4v4"/><circle cx="12" cy="12" r="2"/>',
 ranking:'<path d="M8 3h8v7a4 4 0 0 1-8 0Zm0 2H4v3a4 4 0 0 0 4 4m8-7h4v3a4 4 0 0 1-4 4m-4 2v5m-4 2h8"/>',
 stats:'<path d="M4 3v17h17M8 14l4-5 4 3 5-7"/>',
 club:'<circle cx="9" cy="8" r="3"/><path d="M3 21v-3a6 6 0 0 1 12 0v3m2-16a3 3 0 0 1 0 6m1 3a5 5 0 0 1 3 5v2"/>'
};
const tabs=[['home','Обзор'],['games','Игры'],['ranking','Рейтинг'],['stats','Профиль'],['club','Клуб']];
const icon = id => `<svg viewBox="0 0 24 24" aria-hidden="true">${icons[id]}</svg>`;
const staff = () => ['owner','organizer'].includes(S.club?.role);
const precision = () => S.club?.currency === 'JPY' ? 0 : 2;
const money = (amount, signed=false) => {
 const value=amount || 0, scale=10**precision(), n=Math.abs(value), whole=Math.floor(n/scale), fraction=n%scale;
 return `${value<0?'−':signed&&value>0?'+':''}${whole.toLocaleString('ru-RU')}${fraction?','+String(fraction).padStart(precision(),'0'):''} <span class="currency">${esc(S.club?.currency || 'RUB')}</span>`;
};
const plainMoney = amount => money(amount).replace(/<[^>]*>/g,'');
const inputMoney = amount => String(amount / 10**precision());
const signClass = n => n>0?'positive':n<0?'negative':'';
const initials = n => String(n).split(/\s+/).map(x=>x[0]).slice(0,2).join('').toUpperCase();
const avatar = (name, cls='') => `<span class="avatar ${cls}" aria-hidden="true">${esc(initials(name))}</span>`;
const button = (label,action,cls='',attrs='') => `<button class="button ${cls}" data-action="${action}" ${attrs}>${label}</button>`;
const badge = s => `<span class="badge ${s==='planned'?'warm':''}">${statusNames[s]}</span>`;
const date = s => new Intl.DateTimeFormat('ru-RU',{day:'numeric',month:'short',hour:'2-digit',minute:'2-digit',timeZone:S.club?.timezone || 'Asia/Tashkent'}).format(new Date(s));
const metric = (label,value,hint='',cls='') => `<article class="metric glass"><label>${label}</label><strong class="${cls}">${value}</strong>${hint?`<small>${hint}</small>`:''}</article>`;
const heading = (title,sub,action='') => `<div class="page-heading"><div><h1>${title}</h1><p>${sub}</p></div>${action}</div>`;
let toastTimer, renderSerial=0;
function toast(message){$('#toast').textContent=message;$('#toast').hidden=false;clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').hidden=true,4000);}
async function api(path,body){
 const headers={'Authorization':`tma ${W?.initData || ''}`};
 if(body!==undefined) headers['Content-Type']='application/json';
 const response=await fetch('/api'+path,{method:body===undefined?'GET':'POST',headers,body:body===undefined?undefined:JSON.stringify(body),cache:'no-store'});
 const result=await response.json();
 if(!response.ok) throw new Error(typeof result.detail==='string'?result.detail:'Проверьте заполнение полей.');
 return result;
}
function theme(){
 const override=localStorage.getItem('poker_theme');
 const dark=override?override==='dark':W?.colorScheme==='dark'||(!W&&matchMedia('(prefers-color-scheme: dark)').matches);
 document.body.classList.toggle('dark',dark);
 document.querySelector('meta[name="theme-color"]').content=dark?'#131b18':'#f3f5f4';
}
$('#theme-toggle').onclick=()=>{localStorage.setItem('poker_theme',document.body.classList.contains('dark')?'light':'dark');theme();};
W?.ready(); W?.expand(); W?.onEvent('themeChanged',()=>{localStorage.removeItem('poker_theme');theme();}); theme();
W?.BackButton.onClick(()=>navigate(S.game?'games':'home'));
function nav(){
 const html=tabs.map(([id,label])=>`<button class="nav-button ${S.tab===id?'active':''}" data-tab="${id}" ${S.tab===id?'aria-current="page"':''}>${icon(id)}<span>${label}</span></button>`).join('');
 $('#desktop-nav').innerHTML=html;$('#mobile-nav').innerHTML=html;
 if(S.tab!=='home'||S.game) W?.BackButton.show(); else W?.BackButton.hide();
}
async function load(){
 const result=await api('/clubs');S.clubs=result.clubs;S.user=result.user;
 $('#my-avatar').textContent=initials(result.user.name);
 if(!S.clubs.some(c=>c.id===S.clubId)) S.clubId=S.clubs[0]?.id || null;
 $('#club-select').innerHTML=S.clubs.length?S.clubs.map(c=>`<option value="${c.id}" ${c.id===S.clubId?'selected':''}>${esc(c.name)}</option>`).join(''):'<option>Ваш первый клуб</option>';
 if(S.clubId){
  const club=await api(`/clubs/${S.clubId}`);S.club=club.club;S.members=club.members;S.games=club.games;
  S.stats=await api(`/clubs/${S.clubId}/stats?period=${S.period}`);
 } else {S.club=null;S.members=[];S.games=[];S.stats=null;}
}
async function refresh(){
 const serial=++renderSerial;
 try{await load();if(serial!==renderSerial)return;if(S.game)S.game=await api(`/games/${S.game.id}`);render();}
 catch(e){toast(e.message);$('#content').innerHTML=`<section class="card glass empty"><span class="empty-icon">♠</span><h2>Не удалось открыть клуб</h2><p>${esc(e.message)}</p>${button('Попробовать снова','retry','primary')}</section>`;}
}
function navigate(tab){S.tab=tab;S.game=null;S.page=0;render();window.scrollTo({top:0,behavior:'smooth'});}
function rankingRows(rows,offset=0){return rows.map((r,i)=>`<div class="list-row"><span class="rank">${offset+i+1}</span>${avatar(r.name)}<div class="grow"><div class="name">${esc(r.name)}</div><small>${r.games} игр · среднее ${plainMoney(Math.round(r.profit/r.games))}</small></div><div class="amount ${signClass(r.profit)}">${money(r.profit,true)}</div></div>`).join('');}
function gameRow(g){return `<button class="list-row clickable" data-game="${g.id}"><span class="avatar">♠</span><div class="grow"><div class="name">${esc(g.title)}</div><small>${date(g.starts_at)}</small></div>${badge(g.status)}<span class="muted">›</span></button>`;}
function empty(text,action=''){return `<div class="empty"><span class="empty-icon">♧</span><p>${text}</p>${action}</div>`;}
function pager(count){return count>10?`<div class="page-control">${button('←','prev','small',S.page===0?'disabled':'')}<span>${S.page+1} / ${Math.ceil(count/10)}</span>${button('→','next','small',(S.page+1)*10>=count?'disabled':'')}</div>`:'';}
function home(){
 const own=S.stats.ranking.find(r=>r.id===S.stats.member_id);
 const current=S.games.find(g=>['active','reconciling'].includes(g.status));
 const next=S.games.filter(g=>g.status==='planned').sort((a,b)=>a.starts_at.localeCompare(b.starts_at))[0];
 const completed=S.games.filter(g=>g.status==='completed');
 return heading(`За одним столом`, `Привет, ${esc(S.user.name.split(' ')[0])}. Хороший вечер начинается со своих.`,staff()?button('+ Игра','new-game','primary'):'')+
  `<section class="summary-grid">${metric('Ваш результат',money(own?.profit),own?`${own.games} завершённых игр`:'Пока нет завершённых игр',signClass(own?.profit))}${metric('Сыграно вечеров',completed.length,'За всё время')}${metric('Участников',S.members.length,'В вашем клубе')}</section>`+
  `<div class="section-heading"><h2>Сейчас в клубе</h2><button class="text-button" data-tab="games">Все игры ↗</button></div>`+
  (current||next?hero(current||next):`<section class="card glass">${empty('За столом пока тихо.<br>Запланируйте следующий вечер.',staff()?button('Запланировать игру','new-game','primary'):'')}</section>`)+
  `<div class="two-columns"><section class="card glass"><div class="section-heading"><h2>Результаты клуба</h2><button class="text-button" data-tab="ranking">Рейтинг ↗</button></div>${S.stats.ranking.length?rankingRows(S.stats.ranking.slice(0,3)):empty('Первый результат появится после завершённой игры.')}</section><section class="card glass"><div class="section-heading"><h2>Последние встречи</h2><button class="text-button" data-tab="games">История ↗</button></div>${completed.length?completed.slice(0,3).map(gameRow).join(''):empty('Здесь будут ваши вечера и результаты.')}</section></div>`;
}
function hero(g){return `<section class="game-hero"><span class="eyebrow"><span class="live-dot"></span>${statusNames[g.status].toUpperCase()}</span><h2>${esc(g.title)}</h2><p>${date(g.starts_at)}${g.location?' · '+esc(g.location):''}</p><div class="hero-bottom"><div><label>Стандартный вход</label><strong>${money(g.buyin)}</strong></div><div class="hero-avatars">${S.members.slice(0,4).map(r=>avatar(r.name)).join('')}</div>${button(g.status==='planned'?'К игре ↗':'Открыть стол ↗','open-game','',`data-id="${g.id}"`)}</div></section>`;}
function games(){return heading('Ваши вечера','Планы, живые игры и история встреч.',staff()?button('+ Игра','new-game','primary'):'')+`<section class="card glass">${S.games.length?S.games.slice(S.page*10,(S.page+1)*10).map(gameRow).join(''):empty('Пока не запланировано ни одной игры.')}${pager(S.games.length)}</section>`;}
function ranking(){const rows=S.stats.ranking;return heading('Рейтинг клуба','Суммарная прибыль за завершённые игры.')+`<div class="toolbar"><div class="segmented">${[['all','Всё время'],['month','Месяц'],['season','Сезон']].map(([v,l])=>`<button class="${S.period===v?'active':''}" data-period="${v}">${l}</button>`).join('')}</div></div><section class="card glass">${rows.length?rankingRows(rows.slice(S.page*10,(S.page+1)*10),S.page*10):empty('За этот период ещё нет результатов.')}${pager(rows.length)}</section><p class="fine-print">При равенстве прибыли: больше прибыльных игр, затем порядок вступления.<br>Результаты встреч не являются оценкой мастерства.</p>`;}
function chart(history){
 if(!history.length)return empty('График появится после первой завершённой игры.');
 let sum=0;const values=[0,...history.map(r=>sum+=r.profit)],min=Math.min(...values),max=Math.max(...values),span=max-min||1;
 const points=values.map((v,i)=>[10+i*300/(values.length-1),125-(v-min)*105/span]);
 return `<svg class="chart" viewBox="0 0 320 150" role="img" aria-label="Накопленная прибыль за ${history.length} игр"><defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="currentColor" stop-opacity=".15"/><stop offset="1" stop-color="currentColor" stop-opacity="0"/></linearGradient></defs><path d="M10 20H310 M10 73H310 M10 125H310" class="chart-grid"/><path d="M${points.map(p=>p.join(',')).join(' L')} L310,125 L10,125Z" fill="url(#chart-fill)" style="color:var(--accent)"/><path d="M${points.map(p=>p.join(',')).join(' L')}" class="chart-line"/><text x="10" y="147">Начало</text><text x="310" y="147" text-anchor="end">${history.length} игр</text></svg>`;
}
function stats(){
 const h=S.stats.history,own=S.stats.ranking.find(r=>r.id===S.stats.member_id),best=h.length?Math.max(...h.map(r=>r.profit)):0,worst=h.length?Math.min(...h.map(r=>r.profit)):0;
 return heading('Личный профиль',`${esc(S.user.name)} · только результаты этого клуба`)+`<section class="summary-grid">${metric('Общая прибыль',money(own?.profit),'За выбранный период',signClass(own?.profit))}${metric('Прибыльных игр',own?Math.round(own.wins/own.games*100)+'%':'—',own?`${own.wins} из ${own.games}`:'Игр пока нет')}${metric('Средний результат',own?money(Math.round(own.profit/own.games)):'—','За одну игру')}</section><section class="card glass"><div class="section-heading"><h2>Ваш путь</h2><span class="badge">${own?.games||0} игр</span></div>${chart(h)}<div class="balance"><span>Лучший вечер <b class="positive">${h.length?money(best,true):'—'}</b></span><span>Худший <b class="${signClass(worst)}">${h.length?money(worst,true):'—'}</b></span></div></section><div class="section-heading"><h2>История результатов</h2></div><section class="card glass">${h.length?h.slice().reverse().slice(S.page*10,(S.page+1)*10).map(r=>`<button class="list-row clickable" data-game="${r.id}"><div class="grow"><div class="name">${esc(r.title)}</div><small>${esc(r.date)}</small></div><b class="${signClass(r.profit)}">${money(r.profit,true)}</b></button>`).join(''):empty('Сыграйте первый вечер, чтобы увидеть свой результат.')}${pager(h.length)}</section>`;
}
function club(){return heading('Свой круг',`${esc(S.club.name)} · ${roleNames[S.club.role]}`)+`<section class="card glass"><div class="section-heading"><h2>Настройки клуба</h2><span class="badge">Закрытый клуб</span></div><div class="review-row"><span>Валюта</span><b>${S.club.currency}</b></div><div class="review-row"><span>Часовой пояс</span><b>${esc(S.club.timezone)}</b></div><div class="review-row"><span>Начало сезона</span><b>${S.club.season_start}</b></div><div class="toolbar">${staff()?button('Пригласить в клуб','invite')+button('+ Гость','guest'):''}${button('+ Новый клуб','new-club')}${button('По приглашению','join')}</div></section><div class="section-heading"><h2>Участники · ${S.members.length}</h2></div><section class="card glass">${S.members.map(r=>`<div class="list-row">${avatar(r.name)}<div class="grow"><div class="name">${esc(r.name)}</div><small>${r.tg_id?roleNames[r.role]:'Гость без Telegram'}</small></div>${S.club.role==='owner'&&r.role!=='owner'&&r.tg_id?button(r.role==='organizer'?'Снять роль':'Организатор','role','small',`data-id="${r.id}" data-role="${r.role==='organizer'?'member':'organizer'}"`):''}</div>`).join('')}</section>`;}
function game(){
 const g=S.game, invested=g.players.reduce((a,r)=>a+r.invested,0),cashout=g.players.reduce((a,r)=>a+(r.cashout??0),0),active=g.players.filter(r=>r.cashout===null).length,editable=['active','reconciling'].includes(g.status);
 return `<button class="back-button" data-tab="games">← Все игры</button>`+heading(esc(g.title),`${date(g.starts_at)}${g.location?' · '+esc(g.location):''}`)+`<div class="game-status">${badge(g.status)}</div><div class="summary-grid" style="margin-top:18px">${metric('Всего входов',money(invested),'Подтверждённые операции')}${metric('Кэшауты',money(cashout),'Зафиксированные выходы')}${metric('Ещё за столом',active,`${g.players.length} участников`)}</div><div class="toolbar">${staff()&&['planned','active'].includes(g.status)?button('+ Участник','add-player'):''}${editable?button(staff()?'Вход / докупка':'Заявка на вход','record','primary'):''}${editable&&staff()?button('Кэшаут','cashout'):''}${staff()&&g.status==='planned'?button('Начать игру','status','primary','data-status="active"'):''}${staff()&&g.status==='active'?button('Перейти к сверке','status','','data-status="reconciling"'):''}${staff()&&g.status==='reconciling'?button('Завершить игру','status','primary','data-status="completed"'):''}${staff()&&['planned','active','reconciling'].includes(g.status)?button('Отменить','status','danger','data-status="cancelled"'):''}</div><section class="card glass"><div class="section-heading"><h2>Участники</h2><span class="muted" style="font-size:10px">Входы / результат</span></div>${g.players.length?g.players.map(r=>`<div class="list-row">${avatar(r.name)}<div class="grow"><div class="name">${esc(r.name)}</div><small>Внесено ${plainMoney(r.invested)} · ${r.cashout===null?'За столом':'Кэшаут '+plainMoney(r.cashout)}</small></div><div class="amount ${signClass(r.profit)}">${r.profit===null?'<span class="muted">Ещё играет</span>':money(r.profit,true)}</div></div>`).join(''):empty('Добавьте участников до начала или во время игры.')}${g.status==='reconciling'?`<div class="balance"><span>Входы минус кэшауты</span><b class="${signClass(invested-cashout)}">${money(invested-cashout)}</b></div><p class="field-hint">Для завершения нужны кэшауты всех игроков и нулевая разница.</p>`:''}</section><div class="section-heading"><h2>Журнал операций</h2></div><section class="card glass">${g.operations.length?g.operations.map(o=>`<div class="list-row"><div class="grow"><div class="name">${esc(g.players.find(r=>r.id===o.member_id)?.name||'Игрок')} · ${opNames[o.kind]}</div><small>${date(o.created_at)} · ${({pending:'Ждёт подтверждения',confirmed:'Подтверждено',rejected:'Отклонено',void:'Исправлено'})[o.status]}</small></div><b>${money(o.amount)}</b>${staff()&&o.status==='pending'&&editable?`<div class="operation-actions">${button('✓','decide','small',`data-id="${o.id}" data-accept="true" aria-label="Подтвердить"`)}${button('×','decide','small danger',`data-id="${o.id}" data-accept="false" aria-label="Отклонить"`)}</div>`:''}</div>`).join(''):empty('Все входы, докупки и кэшауты будут здесь.')}</section>`;
}
function render(){
 nav();
 if(!S.club){$('#content').innerHTML=heading('Соберите свой круг','Домашний покер начинается с друзей.')+`<section class="card glass">${empty('Создайте закрытый клуб или введите код приглашения.',button('Создать клуб','new-club','primary')+' '+button('У меня приглашение','join'))}</section>`;return;}
 $('#content').innerHTML=S.game?game():({home,games,ranking,stats,club})[S.tab]();
 if(S.game&&staff()&&['active','reconciling','completed'].includes(S.game.status)&&S.game.operations.some(o=>o.status==='confirmed')){
  $('#content .toolbar').insertAdjacentHTML('beforeend',button('Исправить записи','correct'));
 }
}
function fieldHTML(f){return `<label class="field">${esc(f.label)}${f.options?`<select name="${f.name}" required>${f.options.map(o=>`<option value="${esc(o.value)}" ${o.value===f.value?'selected':''}>${esc(o.label)}</option>`).join('')}</select>`:`<input name="${f.name}" type="${f.type||'text'}" value="${esc(f.value||'')}" ${f.inputmode?`inputmode="${f.inputmode}"`:''} ${f.optional?'':'required'} maxlength="${f.max||80}" autocomplete="off">`}</label>`;}
function form(title,fields,submit,{review=false,label='Сохранить',hint=''}={}){
 const sheet=$('#sheet'),formEl=$('#sheet-form');let reviewed=false,busy=false,values;
 const draftId=`poker-draft:${S.user?.id}:${S.clubId}:${S.game?.id||0}:${title}`;
 let saved;try{saved=JSON.parse(localStorage.getItem(draftId));}catch{}
 const requestKey=saved?.key || crypto.randomUUID();
 if(saved?.values)fields=fields.map(f=>({...f,value:saved.values[f.name]??f.value}));
 const saveDraft=()=>{try{localStorage.setItem(draftId,JSON.stringify({key:requestKey,values:Object.fromEntries(new FormData(formEl))}));}catch{}};
 formEl.oninput=()=>{if(!reviewed)saveDraft();};
 $('#sheet-title').textContent=title;$('#sheet-fields').innerHTML=fields.map(fieldHTML).join('')+(hint?`<p class="field-hint">${esc(hint)}</p>`:'');
 $('#sheet-error').textContent='';$('#sheet-submit').textContent=review?'Проверить':label;$('#sheet-submit').disabled=false;$('#sheet-back').hidden=true;
 $('#sheet-back').onclick=()=>{reviewed=false;$('#sheet-fields').innerHTML=fields.map(f=>fieldHTML({...f,value:values[f.name]})).join('');$('#sheet-back').hidden=true;$('#sheet-submit').textContent='Проверить';};
 formEl.onsubmit=async e=>{
  e.preventDefault();if(busy)return;
  if(!reviewed){saveDraft();values=Object.fromEntries(new FormData(formEl));if(review){reviewed=true;$('#sheet-fields').innerHTML=fields.map(f=>`<div class="review-row"><span>${esc(f.label)}</span><b>${esc(f.options?f.options.find(o=>String(o.value)===values[f.name])?.label:values[f.name])}</b></div>`).join('');$('#sheet-submit').textContent=label;$('#sheet-back').hidden=false;return;}}
  busy=true;$('#sheet-submit').disabled=true;$('#sheet-back').disabled=true;$('#close-sheet').disabled=true;$('#sheet-error').textContent='';
  try{await submit(values,requestKey);localStorage.removeItem(draftId);sheet.close();await refresh();toast('Готово');W?.HapticFeedback?.notificationOccurred('success');}
  catch(err){$('#sheet-error').textContent=err.message;}
  finally{busy=false;$('#sheet-submit').disabled=false;$('#sheet-back').disabled=false;$('#close-sheet').disabled=false;}
 };
 sheet.showModal();setTimeout(()=>sheet.querySelector('input,select')?.focus(),50);
}
$('#close-sheet').onclick=()=>$('#sheet').close();
function confirm(title,text,submit){form(title,[],submit,{label:'Подтвердить',hint:text});}
async function openGame(id){S.game=await api(`/games/${id}`);S.tab='games';S.page=0;render();window.scrollTo(0,0);}
async function act(action,element){
 if(action==='retry'){await refresh();return;}
 if(action==='open-game'){await openGame(Number(element.dataset.id));return;}
 if(action==='prev'||action==='next'){S.page+=action==='next'?1:-1;render();return;}
 if(action==='new-club'){
  const key=crypto.randomUUID();form('Новый клуб',[{name:'name',label:'Название клуба',value:'',max:80},{name:'currency',label:'Валюта',value:'RUB',options:['RUB','UZS','USD','EUR','KZT','JPY'].map(x=>({value:x,label:x}))},{name:'timezone',label:'Часовой пояс',value:'Asia/Tashkent'}],async(v,key)=>{const r=await api('/clubs',{...v,key});S.clubId=r.id;S.game=null;S.tab='home';},{review:true,label:'Создать клуб'});return;
 }
 if(action==='join'){form('Присоединиться',[{name:'token',label:'Код или ссылка приглашения',max:250}],async(v,key)=>{
  let token=v.token.trim();if(token.includes('join_'))token=token.split('join_')[1].split(/[&#?]/)[0];const r=await api('/join',{token});S.clubId=r.id;S.game=null;S.tab='home';},{label:'Вступить в клуб'});return;}
 if(action==='new-game'){
  const key=crypto.randomUUID();const local=new Date(Date.now()-new Date().getTimezoneOffset()*60000).toISOString().slice(0,16);
  form('Новый вечер',[{name:'title',label:'Название',value:'Покерный вечер'},{name:'starts_at',label:'Дата и время на вашем устройстве',type:'datetime-local',value:local},{name:'location',label:'Место или комментарий',optional:true,max:250},{name:'buyin',label:`Стандартный вход, ${S.club.currency}`,inputmode:'decimal',value:'1000'}],async(v,key)=>{const r=await api(`/clubs/${S.clubId}/games`,{...v,starts_at:new Date(v.starts_at).toISOString(),key});S.game=await api(`/games/${r.id}`);S.tab='games';},{review:true,label:'Создать игру',hint:'Дата вводится в часовом поясе устройства; в карточке отображается в часовом поясе клуба.'});return;
 }
 if(action==='invite'){
  const r=await api(`/clubs/${S.clubId}/invite`,{});form('Приглашение в клуб',[{name:'token',label:'Скопируйте и передайте другу',value:r.token,max:100}],async()=>{}, {label:'Закрыть',hint:'Друг сможет вставить этот код в разделе «У меня приглашение».'});return;
 }
 if(action==='guest'){form('Добавить гостя',[{name:'name',label:'Имя гостя'}],v=>api(`/clubs/${S.clubId}/guests`,v),{label:'Добавить'});return;}
 if(action==='role'){confirm('Изменить роль?',`Новая роль: ${roleNames[element.dataset.role]}.`,()=>api(`/clubs/${S.clubId}/roles`,{member_id:Number(element.dataset.id),role:element.dataset.role}));return;}
 if(action==='add-player'){
  const available=S.members.filter(m=>!S.game.players.some(r=>r.id===m.id));if(!available.length){toast('Все участники клуба уже в игре. Гостя можно добавить в разделе «Клуб».');return;}
  form('Участник игры',[{name:'member_id',label:'Кто за столом?',options:available.map(m=>({value:m.id,label:m.name}))}],v=>api(`/games/${S.game.id}/players`,{member_id:Number(v.member_id)}),{label:'Добавить в игру'});return;
 }
 if(action==='correct'){
  const key=crypto.randomUUID(),ops=S.game.operations.filter(o=>o.status==='confirmed');
  const fields=ops.map(o=>({name:'op_'+o.id,label:`${S.game.players.find(r=>r.id===o.member_id)?.name} · ${opNames[o.kind]}, ${S.club.currency}`,value:inputMoney(o.amount),inputmode:'decimal',max:30}));
  fields.push({name:'reason',label:'Причина исправления',max:500});
  form('Исправить записи',fields,(v,key)=>{
   const amounts={};for(const o of ops)if(v['op_'+o.id]!==inputMoney(o.amount))amounts[o.id]=v['op_'+o.id];
   if(!Object.keys(amounts).length)throw new Error('Измените хотя бы одну сумму.');
   return api(`/games/${S.game.id}/corrections`,{amounts,reason:v.reason,key});
  },{review:true,label:'Записать исправление',hint:'Исходные записи сохранятся в журнале. Для завершённой игры итоговый баланс должен остаться нулевым.'});return;
 }
 if(action==='record'||action==='cashout'){
  const key=crypto.randomUUID(),cash=action==='cashout';
  const available=S.game.players.filter(r=>r.cashout===null&&(cash||staff()||r.id===S.game.member_id));
  if(!available.length){toast('Нет подходящих игроков. Попросите организатора добавить вас в игру.');return;}
  const fields=[{name:'member_id',label:'Участник',options:available.map(r=>({value:r.id,label:r.name}))},...(!cash?[{name:'kind',label:'Операция',options:[{value:'buyin',label:'Первый вход'},{value:'rebuy',label:'Докупка'}]}]:[]),{name:'amount',label:`Сумма, ${S.club.currency}`,inputmode:'decimal',value:cash?'0':inputMoney(S.game.buyin)}];
  form(cash?'Зафиксировать выход':staff()?'Вход / докупка':'Заявка на вход',fields,(v,key)=>api(`/games/${S.game.id}/operations`,{...v,member_id:Number(v.member_id),kind:cash?'cashout':v.kind,key}),{review:true,label:staff()?'Подтвердить запись':'Отправить заявку',hint:cash?'Кэшаут — окончательная стоимость фишек при выходе. Нулевой кэшаут допустим.':staff()?'Сумма будет сразу учтена в игре.':'Сумма учитывается только после подтверждения организатором.'});return;
 }
 if(action==='status'){const next=element.dataset.status;confirm(statusNames[next],next==='completed'?'Игра завершится только после сверки всех кэшаутов и подтверждения заявок.':next==='cancelled'?'Игра будет отменена. Её результаты не попадут в рейтинг.':'Подтвердите изменение статуса игры.',()=>api(`/games/${S.game.id}/status`,{status:next}));return;}
 if(action==='decide'){confirm(element.dataset.accept==='true'?'Подтвердить заявку?':'Отклонить заявку?','Проверьте игрока и сумму в журнале операций.',()=>api(`/operations/${element.dataset.id}/decision`,{accept:element.dataset.accept==='true'}));}
}
document.addEventListener('click',async e=>{
 const target=e.target.closest('[data-tab],[data-game],[data-action],[data-period]');if(!target)return;
 try{
  if(target.dataset.tab){navigate(target.dataset.tab);return;}
  if(target.dataset.game){await openGame(Number(target.dataset.game));return;}
  if(target.dataset.period){S.period=target.dataset.period;S.page=0;S.stats=await api(`/clubs/${S.clubId}/stats?period=${S.period}`);render();return;}
  if(target.dataset.action)await act(target.dataset.action,target);
 }catch(err){toast(err.message);}
});
$('#club-select').onchange=async e=>{S.clubId=Number(e.target.value);S.game=null;S.page=0;await refresh();};
async function boot(){
 try{const config=await api('/config');$('#demo-banner').hidden=!config.demo;await refresh();}
 catch(e){$('#content').innerHTML=`<section class="card glass empty"><h2>Не удалось загрузить приложение</h2><p>${esc(e.message)}</p>${button('Повторить','retry','primary')}</section>`;}
}
boot();
