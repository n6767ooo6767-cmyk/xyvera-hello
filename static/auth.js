const SUPABASE_URL = "https://xrahbkohfbtncasqncas.supabase.co";
const SUPABASE_KEY = "sb_publishable_cSUARkOBMBka6JZ3QbT0RQ_s8K4ASkm";
const sb = window.supabase.createClient(SUPABASE_URL, SUPABASE_KEY);

function msg(text, ok=false){ const el=document.getElementById('message'); if(el){el.textContent=text;el.className=ok?'success':'error';} }

async function register(){
  const email=document.getElementById('email').value.trim();
  const password=document.getElementById('password').value;
  if(!email || password.length<6){ msg('Введите email и пароль минимум из 6 символов.'); return; }
  const {error}=await sb.auth.signUp({email,password});
  if(error){msg(error.message);return;}
  msg('Аккаунт создан. Если включено подтверждение email — проверь почту.',true);
}

async function login(){
  const email=document.getElementById('email').value.trim();
  const password=document.getElementById('password').value;
  const {error}=await sb.auth.signInWithPassword({email,password});
  if(error){msg(error.message);return;}
  location.href='/profile';
}

async function logout(){ await sb.auth.signOut(); location.href='/'; }

async function loadProfile(){
  const {data:{user}}=await sb.auth.getUser();
  if(!user){location.href='/login';return null;}
  const {data,error}=await sb.from('profiles').select('*').eq('user_id',user.id).maybeSingle();
  if(error){msg(error.message);return user;}
  if(data){
    for(const id of ['username','display_name','bio','avatar_url']){const el=document.getElementById(id);if(el)el.value=data[id]||'';}
  }
  return user;
}

async function saveProfile(){
  const {data:{user}}=await sb.auth.getUser();
  if(!user){location.href='/login';return;}
  const username=document.getElementById('username').value.trim().toLowerCase();
  if(!/^[a-z0-9_-]{3,30}$/.test(username)){msg('Username: 3–30 символов, только a-z, 0-9, _ или -.');return;}
  const payload={user_id:user.id,username,display_name:document.getElementById('display_name').value.trim(),bio:document.getElementById('bio').value.trim(),avatar_url:document.getElementById('avatar_url').value.trim(),updated_at:new Date().toISOString()};
  const {error}=await sb.from('profiles').upsert(payload,{onConflict:'user_id'});
  if(error){msg(error.message);return;}
  msg('Профиль сохранён ✨',true);
}

async function addLink(){
  const {data:{user}}=await sb.auth.getUser(); if(!user){location.href='/login';return;}
  const title=prompt('Название ссылки:'); if(!title)return;
  const url=prompt('URL (например https://youtube.com/...):'); if(!url)return;
  if(!/^https?:\/\//i.test(url)){msg('Ссылка должна начинаться с http:// или https://');return;}
  const {data}=await sb.from('profile_links').select('position').eq('user_id',user.id).order('position',{ascending:false}).limit(1);
  const position=(data?.[0]?.position??-1)+1;
  const {error}=await sb.from('profile_links').insert({user_id:user.id,title,url,position});
  if(error){msg(error.message);return;} await loadLinks();
}

async function loadLinks(){
  const box=document.getElementById('links'); if(!box)return;
  const {data:{user}}=await sb.auth.getUser(); if(!user)return;
  const {data,error}=await sb.from('profile_links').select('*').eq('user_id',user.id).order('position');
  if(error){msg(error.message);return;}
  box.innerHTML='';
  for(const link of data||[]){const row=document.createElement('div');row.className='link-row';row.innerHTML=`<span>${escapeHtml(link.title)}</span><a href="${escapeAttr(link.url)}" target="_blank" rel="noopener">${escapeHtml(link.url)}</a><button class="button" onclick="removeLink(${link.id})">Удалить</button>`;box.appendChild(row);}
}
async function removeLink(id){if(!confirm('Удалить ссылку?'))return;const {error}=await sb.from('profile_links').delete().eq('id',id);if(error){msg(error.message);return;}loadLinks();}

async function loadPublicProfile(username){
  const {data:p,error}=await sb.from('profiles').select('username,display_name,bio,avatar_url').eq('username',username).maybeSingle();
  if(error||!p){msg('Профиль не найден.');return;}
  document.getElementById('display').textContent=p.display_name||p.username;
  document.getElementById('bio').textContent=p.bio||'';
  const avatar=document.getElementById('avatar'); if(p.avatar_url){avatar.src=p.avatar_url;avatar.hidden=false;}
  const {data:links}=await sb.from('profile_links').select('title,url').eq('user_id',p.user_id).order('position');
  const box=document.getElementById('public-links'); box.innerHTML=''; for(const l of links||[]){const a=document.createElement('a');a.className='button link-card';a.href=l.url;a.target='_blank';a.rel='noopener';a.textContent=l.title;box.appendChild(a);}
}
function escapeHtml(s){return String(s).replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));}
function escapeAttr(s){return escapeHtml(s);}
