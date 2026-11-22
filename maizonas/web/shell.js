'use strict';
(()=>{
 const page=location.pathname.startsWith('/settings')?'settings':location.pathname.startsWith('/downloads')||location.pathname.startsWith('/passwords')?'downloads':location.pathname.startsWith('/convert')?'convert':'collection';
 document.body.classList.add('maizonas','page-'+page);
 const content=document.createElement('div');content.className='maizo-content';
 for(const child of [...document.body.children])if(child.tagName!=='SCRIPT')content.append(child);
 document.body.prepend(content);
 const old=content.querySelector('header.topbar,header:has(.brand)');if(old)old.hidden=true;
 const bar=document.createElement('header');bar.className='maizo-header';
 const brand=document.createElement('a');brand.className='maizo-brand';brand.href='/';brand.innerHTML='<span aria-hidden="true">▥</span><span>MaizoNAS<small>SEU SERVIDOR, EM UM LUGAR</small></span>';bar.append(brand);
 const nav=document.createElement('nav');nav.setAttribute('aria-label','Navegação principal');
 for(const [key,title,url]of [['collection','Coleção','/'],['downloads','Downloads','/downloads'],['convert','Conversor','/convert'],['settings','Servidor','/settings']]){const a=document.createElement('a');a.textContent=title;a.href=url;if(page===key)a.setAttribute('aria-current','page');nav.append(a)}bar.append(nav);
 const state=document.createElement('a');state.className='maizo-server-state';state.href='/settings';state.textContent='● Painel do servidor';bar.append(state);document.body.prepend(bar);
 if(page==='collection'){const refresh=content.querySelector('#refresh');if(refresh){const button=document.createElement('button');button.className='maizo-refresh';button.textContent='↻ Atualizar';button.onclick=()=>refresh.click();bar.append(button)}}
 const footer=document.createElement('footer');footer.className='maizo-footer';footer.textContent='MaizoNAS 2 · Processamento local · '+location.host;content.append(footer);
 document.title='MaizoNAS · '+({collection:'Coleção',downloads:'Downloads',convert:'Conversor',settings:'Servidor'}[page]);
})();
