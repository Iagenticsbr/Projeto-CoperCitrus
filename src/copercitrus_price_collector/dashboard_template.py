"""Modelo HTML do painel.

Fica separado do gerador porque e um documento longo: misturar template e
logica de leitura da base torna os dois dificeis de revisar.
"""

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap">
<title>Inteligência de Preços CoperCitrus</title>
<style>
  /* Cores da marca iagentics, lidas dos tokens do proprio site:
     ink #131723, paper #f8f8f8, violet #7607e8, indigo #6020ee,
     periwinkle #6c66f3, blue #6693f8, sky #55afed.
     Verde, amarelo e vermelho nao existem na marca e continuam aqui porque
     sao semanticos: barato, mediana e caro precisam ser lidos sem legenda. */
  :root {
    --ink:#131723; --paper:#f8f8f8;
    --violet:#7607e8; --indigo:#6020ee; --periwinkle:#6c66f3;
    --blue:#6693f8; --sky:#55afed;
    --fundo:#0e111a; --painel:#171c2a; --painel2:#1d2333; --linha:#2a3145;
    --texto:var(--paper); --suave:#8b93a8; --fraco:#6b7385;
    --azul:var(--blue); --roxo:var(--periwinkle);
    --verde:#3ddc97; --amarelo:#ffc861; --vermelho:#ff6b7a;
    /* Superficie reta e controle em pilula: e assim que a marca se apresenta. */
    --r-surf:4px; --r-ctrl:999px;
  }
  * { box-sizing:border-box; }
  html { scroll-behavior:smooth; }
  body {
    margin:0; background:var(--fundo); color:var(--texto);
    font:15px/1.55 "Space Grotesk","Segoe UI",-apple-system,system-ui,sans-serif;
    -webkit-font-smoothing:antialiased;
  }
  .capa {
    background:
      radial-gradient(1100px 380px at 8% -30%, rgba(118,7,232,.26), transparent 65%),
      radial-gradient(900px 340px at 92% -20%, rgba(102,147,248,.18), transparent 60%),
      linear-gradient(180deg, #151a2b 0%, var(--fundo) 100%);
    border-bottom:1px solid var(--linha); padding:26px 30px 22px;
    position:relative;
  }
  /* Faixa da marca: violeta ao ceu, a mesma sequencia do site. */
  .capa::before {
    content:""; position:absolute; left:0; right:0; top:0; height:3px;
    background:linear-gradient(90deg,var(--violet),var(--indigo),
      var(--periwinkle),var(--blue),var(--sky));
  }
  .capa-topo { display:flex; justify-content:space-between; align-items:flex-start;
               gap:20px; flex-wrap:wrap; max-width:1520px; margin:0 auto; }
  h1 { font-size:23px; margin:0; font-weight:650; letter-spacing:-.3px; }
  .sub { color:var(--suave); font-size:13px; margin-top:5px; }
  .selo { display:inline-flex; align-items:center; gap:7px; background:rgba(102,147,248,.12);
          border:1px solid rgba(102,147,248,.38); color:var(--blue);
          padding:6px 13px; border-radius:99px; font-size:12.5px; font-weight:600; }
  main { padding:22px 30px 70px; max-width:1520px; margin:0 auto; }

  .filtros { display:flex; gap:13px; flex-wrap:wrap; align-items:end;
             background:var(--painel); border:1px solid var(--linha);
             border-radius:var(--r-surf); padding:15px 17px; margin-bottom:22px; }
  .filtros label { display:block; font-size:11.5px; color:var(--suave);
                   margin-bottom:6px; text-transform:uppercase; letter-spacing:.5px; }
  select, input { background:var(--fundo); color:var(--texto); border:1px solid var(--linha);
                  border-radius:var(--r-ctrl); padding:9px 15px; font-size:14px; min-width:172px; }
  select:focus, input:focus { outline:none; border-color:var(--azul); }
  button { background:var(--violet); color:var(--paper); border:0; border-radius:var(--r-ctrl);
           padding:9px 19px; font-size:14px; font-weight:650; cursor:pointer; }
  button.limpar { background:transparent; color:var(--suave); border:1px solid var(--linha); }
  button.limpar:hover { color:var(--texto); border-color:var(--azul); }

  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(196px,1fr));
           gap:14px; margin-bottom:24px; }
  .card { background:linear-gradient(160deg,var(--painel2),var(--painel));
          border:1px solid var(--linha); border-radius:var(--r-surf); padding:16px 18px;
          position:relative; overflow:hidden; }
  .card::after { content:""; position:absolute; left:0; top:0; bottom:0; width:3px;
                 background:var(--cor,var(--azul)); }
  .card .rotulo { color:var(--suave); font-size:11.5px; text-transform:uppercase;
                  letter-spacing:.6px; font-weight:600; }
  .card .valor { font-size:29px; font-weight:680; margin-top:7px; letter-spacing:-.6px;
                 color:var(--cor,var(--texto)); }
  .card .nota { color:var(--suave); font-size:12px; margin-top:5px; }

  .abas { display:flex; gap:5px; margin-bottom:18px; flex-wrap:wrap;
          border-bottom:1px solid var(--linha); padding-bottom:0; }
  .aba { padding:10px 17px; cursor:pointer; font-size:14px; font-weight:550;
         background:transparent; color:var(--suave); border:0;
         border-bottom:2px solid transparent; margin-bottom:-1px; }
  .aba:hover { color:var(--texto); }
  .aba.ativa { color:var(--azul); border-bottom-color:var(--azul); }

  .painel[hidden] { display:none; }
  .grade { display:grid; grid-template-columns:repeat(auto-fit,minmax(430px,1fr)); gap:18px; }
  .bloco { background:var(--painel); border:1px solid var(--linha);
           border-radius:var(--r-surf); padding:18px 20px; }
  .bloco.largo { grid-column:1/-1; }
  h2 { font-size:15.5px; margin:0 0 4px; font-weight:640; }
  .legenda { color:var(--suave); font-size:12.5px; margin-bottom:15px; }

  table { width:100%; border-collapse:collapse; font-size:13.5px; }
  th,td { text-align:left; padding:9px 10px; border-bottom:1px solid var(--linha); white-space:nowrap; }
  th { color:var(--suave); font-weight:640; font-size:11.5px;
       text-transform:uppercase; letter-spacing:.5px; }
  tbody tr:hover { background:rgba(102,147,248,.07); }
  td.num,th.num { text-align:right; font-variant-numeric:tabular-nums; }
  .rolagem { overflow-x:auto; }
  .neg { color:var(--verde); font-weight:600; } .pos { color:var(--vermelho); font-weight:600; }
  .tag { font-size:11px; padding:3px 9px; border-radius:99px; font-weight:600;
         border:1px solid var(--linha); color:var(--suave); }
  .tag.COMPATIVEL { color:var(--verde); border-color:rgba(61,220,151,.42); background:rgba(61,220,151,.10); }
  .tag.SIMILAR { color:var(--periwinkle); border-color:rgba(108,102,243,.45); background:rgba(108,102,243,.12); }
  .tag.DIVERGENTE { color:var(--vermelho); border-color:rgba(255,107,122,.4); background:rgba(255,107,122,.08); }
  /* Preco fora da faixa do proprio SKU. Marcado, nunca removido: quem le
     precisa ver que a oferta existe e por que ela e suspeita. */
  .alerta { font-size:11px; padding:2px 8px; border-radius:var(--r-ctrl);
            font-weight:650; margin-left:7px; white-space:nowrap; }
  .alerta.abaixo { color:var(--amarelo); background:rgba(255,200,97,.12);
                   border:1px solid rgba(255,200,97,.4); }
  .alerta.acima { color:var(--vermelho); background:rgba(255,107,122,.12);
                  border:1px solid rgba(255,107,122,.4); }
  tr.suspeita td { background:rgba(255,200,97,.045); }
  .vazio { color:var(--suave); padding:34px; text-align:center; }
  svg { display:block; width:100%; height:auto; }
  a { color:var(--azul); text-decoration:none; } a:hover { text-decoration:underline; }
  .posicao { display:inline-flex; width:22px; height:22px; border-radius:6px;
             background:var(--linha); color:var(--suave); align-items:center;
             justify-content:center; font-size:11.5px; font-weight:700; margin-right:8px; }
  .posicao.top { background:rgba(255,200,97,.16); color:var(--amarelo); }
  .oportunidade { display:flex; justify-content:space-between; align-items:center;
                  gap:14px; padding:13px 0; border-bottom:1px solid var(--linha); }
  .oportunidade:last-child { border-bottom:0; }
  .oportunidade .nome { font-weight:560; }
  .oportunidade .detalhe { color:var(--suave); font-size:12.5px; margin-top:3px; }
  .preferida { color:var(--verde); font-weight:640; }
  .preferida::before { content:"\2605"; margin-right:5px; font-size:11px; }
  .economia { font-size:19px; font-weight:680; color:var(--verde); white-space:nowrap; }
</style>
</head>
<body>

<div class="capa">
  <div class="capa-topo">
    <div>
      <h1>Inteligência de Preços</h1>
      <div class="sub" id="rodape"></div>
    </div>
    <div style="text-align:right">
      <div class="selo" id="selo">carregando</div>
      <div class="sub" id="contagem" style="margin-top:9px"></div>
    </div>
  </div>
</div>

<main>
  <div class="filtros">
    <div><label>Fabricante</label><select id="f-marca"></select></div>
    <div><label>Produto</label><select id="f-produto"></select></div>
    <div><label>Loja</label><select id="f-loja"></select></div>
    <div><label>Status</label><select id="f-classe"></select></div>
    <div><label>Preço</label><select id="f-alerta">
      <option value="">Todos</option>
      <option value="alerta">Só os fora da faixa</option>
      <option value="ok">Só os dentro da faixa</option>
    </select></div>
    <div><label>Preço máximo</label><input id="f-preco" type="number" min="0" placeholder="sem limite"></div>
    <button class="limpar" id="limpar">Limpar filtros</button>
  </div>

  <div class="cards" id="indicadores"></div>

  <div class="abas">
    <button class="aba ativa" data-alvo="p-visao">Visão geral</button>
    <button class="aba" data-alvo="p-oportunidades">Oportunidades</button>
    <button class="aba" data-alvo="p-fabricante">Fabricantes</button>
    <button class="aba" data-alvo="p-loja">Lojas</button>
    <button class="aba" data-alvo="p-dispersao">Dispersão</button>
    <button class="aba" data-alvo="p-ofertas">Ofertas</button>
    <button class="aba" data-alvo="p-historico">Evolução</button>
  </div>

  <section class="painel" id="p-visao">
    <div class="grade">
      <div class="bloco largo">
        <h2>Faixa de preço por produto</h2>
        <div class="legenda">Cada linha vai do menor ao maior preço encontrado.
          O ponto amarelo marca a mediana, que é a referência real de mercado.</div>
        <div id="g-faixa"></div>
      </div>
      <div class="bloco largo">
        <h2>Resumo por produto</h2>
        <div class="legenda">Ordenado pelo maior teto de preço.</div>
        <div class="rolagem"><table id="t-resumo"></table></div>
      </div>
    </div>
  </section>

  <section class="painel" id="p-oportunidades" hidden>
    <div class="grade">
      <div class="bloco">
        <h2>Maior economia possível</h2>
        <div class="legenda">Diferença entre a mediana do mercado e a melhor oferta.
          É quanto se deixa na mesa comprando no preço médio.</div>
        <div id="l-economia"></div>
      </div>
      <div class="bloco">
        <h2>Produtos que pedem conferência</h2>
        <div class="legenda">Dispersão acima de 50% costuma indicar anúncio de item
          diferente misturado na busca, ou oportunidade real.</div>
        <div id="l-conferir"></div>
      </div>
      <div class="bloco largo">
        <h2>Melhor oferta por produto</h2>
        <div class="rolagem"><table id="t-melhor"></table></div>
      </div>
    </div>
  </section>

  <section class="painel" id="p-fabricante" hidden>
    <div class="grade">
      <div class="bloco">
        <h2>Preço médio por fabricante</h2>
        <div class="legenda">Média das ofertas do recorte atual.</div>
        <div id="g-marca"></div>
      </div>
      <div class="bloco">
        <h2>Detalhe por fabricante</h2>
        <div class="legenda">&nbsp;</div>
        <div class="rolagem"><table id="t-marca"></table></div>
      </div>
    </div>
  </section>

  <section class="painel" id="p-loja" hidden>
    <div class="grade">
      <div class="bloco largo">
        <h2>Posição frente à mediana</h2>
        <div class="legenda">Verde indica loja abaixo do mercado. Vermelho, acima.</div>
        <div class="rolagem"><table id="t-loja"></table></div>
      </div>
    </div>
  </section>

  <section class="painel" id="p-dispersao" hidden>
    <div class="grade">
      <div class="bloco">
        <h2>Coeficiente de variação</h2>
        <div class="legenda">Verde é mercado consolidado. Vermelho pede conferência.</div>
        <div id="g-cv"></div>
      </div>
      <div class="bloco">
        <h2>Estatística por produto</h2>
        <div class="legenda">&nbsp;</div>
        <div class="rolagem"><table id="t-estat"></table></div>
      </div>
    </div>
  </section>

  <section class="painel" id="p-ofertas" hidden>
    <div class="bloco largo">
      <h2>Ofertas coletadas</h2>
      <div class="legenda" id="c-ofertas"></div>
      <div class="rolagem"><table id="t-ofertas"></table></div>
    </div>
  </section>

  <section class="painel" id="p-historico" hidden>
    <div id="hist-conteudo"></div>
  </section>
</main>

<script>
const DADOS = __DADOS__;
const brl = v => v == null ? "-" : v.toLocaleString("pt-BR",{style:"currency",currency:"BRL"});
const pct = v => v == null ? "-" : v.toFixed(1).replace(".",",") + "%";
const esc = t => String(t ?? "").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const corta = (t,n) => { t = String(t ?? ""); return t.length > n ? t.slice(0,n-1) + "…" : t; };

const marcaPorProduto = {};
DADOS.produtos.forEach(p => { marcaPorProduto[p.produto] = p.marca || "Sem fabricante"; });
DADOS.ofertas.forEach(o => { if (!o.marca) o.marca = marcaPorProduto[o.produto] || "Sem fabricante"; });

const filtros = {marca:"",produto:"",loja:"",fonte:"",classe:"",preco:"",alerta:""};

const ofertasFiltradas = () => DADOS.ofertas.filter(o =>
  o.preco != null &&
  (!filtros.marca   || o.marca === filtros.marca) &&
  (!filtros.produto || o.produto === filtros.produto) &&
  (!filtros.loja    || (o.loja || "Loja não informada") === filtros.loja) &&
  (!filtros.fonte   || o.fonte === filtros.fonte) &&
  (!filtros.classe  || o.classificacao === filtros.classe) &&
  (!filtros.alerta  || (filtros.alerta === "alerta" ? !!o.alerta_preco : !o.alerta_preco)) &&
  (!filtros.preco   || o.preco <= Number(filtros.preco)));

function estatistica(valores) {
  if (!valores.length) return null;
  const s = [...valores].sort((a,b)=>a-b);
  const q = f => { const p=(s.length-1)*f, i=Math.floor(p), w=p-i;
                   return s[i]*(1-w)+s[Math.min(i+1,s.length-1)]*w; };
  const media = s.reduce((a,b)=>a+b,0)/s.length;
  const dp = Math.sqrt(s.reduce((a,b)=>a+(b-media)**2,0)/s.length);
  return {n:s.length,min:s[0],max:s[s.length-1],mediana:q(0.5),p25:q(0.25),
          p75:q(0.75),media,dp,cv:media?dp/media*100:0};
}

const agrupa = (lista,chave) => lista.reduce((mapa,item) => {
  const k = chave(item) || "Sem identificacao"; (mapa[k] = mapa[k] || []).push(item); return mapa;
}, {});

function preencheSelect(id,valores,rotulo,formata) {
  document.getElementById(id).innerHTML =
    `<option value="">${rotulo}</option>` +
    valores.map(v=>`<option value="${esc(v)}">${formata?formata(v):esc(v)}</option>`).join("");
}
const unicos = (l,c) => [...new Set(l.map(c).filter(Boolean))].sort();

function barras(itens, formata, corPadrao) {
  if (!itens.length) return '<div class="vazio">Sem dados para o filtro atual.</div>';
  const max = Math.max(...itens.map(i=>i.valor)) || 1;
  const h = 30, altura = itens.length*h + 12, rotulo = 190, pista = 430;
  return `<svg viewBox="0 0 760 ${altura}">
    <defs><linearGradient id="gr" x1="0" x2="1">
      <stop offset="0" stop-color="${corPadrao}" stop-opacity=".95"></stop>
      <stop offset="1" stop-color="${corPadrao}" stop-opacity=".45"></stop>
    </linearGradient></defs>` + itens.map((item,i) => {
    const y = i*h + 8;
    const largura = Math.max(3,(item.valor/max)*pista);
    const cor = item.cor ? item.cor : "url(#gr)";
    return `<text x="0" y="${y+14}" fill="#8ea3b8" font-size="12.5">${esc(corta(item.rotulo,26))}</text>
      <rect x="${rotulo}" y="${y+3}" width="${largura}" height="15" rx="5" fill="${cor}"></rect>
      <text x="${rotulo+largura+9}" y="${y+15}" fill="#eef4fa" font-size="12.5" font-weight="600">${formata(item.valor)}</text>`;
  }).join("") + `</svg>`;
}

function faixaPrecos(linhas) {
  if (!linhas.length) return '<div class="vazio">Sem dados para o filtro atual.</div>';
  const max = Math.max(...linhas.map(l=>l.max)) || 1;
  const h = 34, altura = linhas.length*h + 16, x0 = 215, pista = 400;
  const px = v => x0 + (v/max)*pista;
  return `<svg viewBox="0 0 760 ${altura}">` + linhas.map((l,i) => {
    const y = i*h + 12;
    return `<text x="0" y="${y+5}" fill="#8ea3b8" font-size="12.5">${esc(corta(l.produto,28))}</text>
      <line x1="${px(l.min)}" y1="${y}" x2="${px(l.max)}" y2="${y}" stroke="#2b3d51" stroke-width="8" stroke-linecap="round"></line>
      <line x1="${px(l.p25)}" y1="${y}" x2="${px(l.p75)}" y2="${y}" stroke="#4ea3ff" stroke-width="8" stroke-linecap="round" opacity=".55"></line>
      <circle cx="${px(l.min)}" cy="${y}" r="5.5" fill="#2fd6a0"></circle>
      <circle cx="${px(l.mediana)}" cy="${y}" r="5.5" fill="#ffc861"></circle>
      <circle cx="${px(l.max)}" cy="${y}" r="5.5" fill="#ff6b7a"></circle>
      <text x="${Math.min(px(l.max)+11,660)}" y="${y+4}" fill="#8ea3b8" font-size="11.5">${brl(l.min)} – ${brl(l.max)}</text>`;
  }).join("") + `</svg>
  <div class="legenda" style="margin-top:10px">
    <span style="color:#2fd6a0">●</span> menor preco &nbsp;
    <span style="color:#ffc861">●</span> mediana &nbsp;
    <span style="color:#ff6b7a">●</span> maior preco &nbsp;
    <span style="color:#4ea3ff">▬</span> metade central das ofertas</div>`;
}

function tabela(id,colunas,linhas,classeLinha) {
  const alvo = document.getElementById(id);
  if (!alvo) return;
  if (!linhas.length) { alvo.innerHTML = `<tr><td class="vazio">Sem dados no recorte.</td></tr>`; return; }
  alvo.innerHTML =
    "<thead><tr>" + colunas.map(c=>`<th class="${c.num?'num':''}">${c.titulo}</th>`).join("") + "</tr></thead>" +
    "<tbody>" + linhas.map((l,i)=>`<tr class="${classeLinha?classeLinha(l):''}">` + colunas.map(c=>`<td class="${c.num?'num':''}">${c.valor(l,i)}</td>`).join("") + "</tr>").join("") + "</tbody>";
}

// COMPATIVEL e SIMILAR sao os nomes internos; na tela eles precisam dizer o
// que significam para quem compra, nao como o codigo classifica.
const ROTULOS_CLASSE = {
  COMPATIVEL:"Exato", SIMILAR:"Similar", DIVERGENTE:"Divergente",
};
function rotuloClasse(valor) {
  return esc(ROTULOS_CLASSE[(valor||"").toUpperCase()] || "sem classificação");
}
function marcaAlerta(o) {
  if (!o.alerta_preco) return "";
  const texto = o.alerta_preco==="abaixo" ? "muito abaixo" : "muito acima";
  return `<span class="alerta ${esc(o.alerta_preco)}" title="Fora da faixa dos demais preços deste SKU">${texto}</span>`;
}

function render() {
  const ofertas = ofertasFiltradas();
  const geral = estatistica(ofertas.map(o=>o.preco));
  const lojas = new Set(ofertas.map(o=>o.loja).filter(Boolean));
  const produtos = new Set(ofertas.map(o=>o.produto));

  document.getElementById("contagem").textContent =
    `${ofertas.length} ofertas · ${produtos.size} produtos · ${lojas.size} lojas`;

  const porProduto = agrupa(ofertas,o=>o.produto);
  const faixas = Object.entries(porProduto).map(([produto,itens]) => {
    const e = estatistica(itens.map(i=>i.preco));
    const barata = itens.reduce((a,b)=>a.preco<=b.preco?a:b);
    return {produto,...e,economia:e.mediana-e.min,melhor:barata};
  }).sort((a,b)=>b.max-a.max);

  const economiaTotal = faixas.reduce((a,f)=>a+Math.max(0,f.economia),0);

  document.getElementById("indicadores").innerHTML = [
    {rotulo:"Ofertas",valor:ofertas.length,nota:`${produtos.size} produtos · ${lojas.size} lojas`,cor:"var(--azul)"},
    {rotulo:"Menor preço",valor:geral?brl(geral.min):"-",nota:"melhor oferta do recorte",cor:"var(--verde)"},
    {rotulo:"Mediana",valor:geral?brl(geral.mediana):"-",nota:"referência de mercado",cor:"var(--amarelo)"},
    {rotulo:"Maior preço",valor:geral?brl(geral.max):"-",nota:"teto do recorte",cor:"var(--vermelho)"},
    {rotulo:"Economia possível",valor:brl(economiaTotal),nota:"mediana menos melhor oferta",cor:"var(--verde)"},
    {rotulo:"Dispersão",valor:geral?pct(geral.cv):"-",nota:"variação dos preços",cor:"var(--roxo)"},
    {rotulo:"Exatos / Similares",
     valor:`${ofertas.filter(o=>o.classificacao==="COMPATIVEL").length} / ${ofertas.filter(o=>o.classificacao==="SIMILAR").length}`,
     nota:"similar = mesma função e voltagem",cor:"var(--periwinkle)"},
    {rotulo:"Preços a conferir",valor:ofertas.filter(o=>o.alerta_preco).length,
     nota:"fora da faixa do próprio SKU",cor:"var(--amarelo)"},
  ].map(c=>`<div class="card" style="--cor:${c.cor}"><div class="rotulo">${c.rotulo}</div>
     <div class="valor">${c.valor}</div><div class="nota">${c.nota}</div></div>`).join("");

  document.getElementById("g-faixa").innerHTML = faixaPrecos(faixas.slice(0,16));
  tabela("t-resumo",[
    {titulo:"Produto",valor:l=>esc(corta(l.produto,44))},
    {titulo:"Ofertas",num:true,valor:l=>l.n},
    {titulo:"Menor",num:true,valor:l=>`<span class="neg">${brl(l.min)}</span>`},
    {titulo:"Mediana",num:true,valor:l=>brl(l.mediana)},
    {titulo:"Maior",num:true,valor:l=>brl(l.max)},
    {titulo:"Dispersão",num:true,valor:l=>pct(l.cv)},
  ],faixas);

  // Oportunidades
  const economias = [...faixas].filter(f=>f.n>1&&f.economia>0).sort((a,b)=>b.economia-a.economia).slice(0,7);
  document.getElementById("l-economia").innerHTML = economias.length ? economias.map(f=>
    `<div class="oportunidade"><div>
       <div class="nome">${esc(corta(f.produto,40))}</div>
       <div class="detalhe">melhor ${brl(f.min)} · mediana ${brl(f.mediana)} · ${f.n} ofertas</div>
     </div><div class="economia">${brl(f.economia)}</div></div>`).join("")
    : '<div class="vazio">Sem comparação suficiente no recorte.</div>';

  const conferir = [...faixas].filter(f=>f.n>1&&f.cv>50).sort((a,b)=>b.cv-a.cv).slice(0,7);
  document.getElementById("l-conferir").innerHTML = conferir.length ? conferir.map(f=>
    `<div class="oportunidade"><div>
       <div class="nome">${esc(corta(f.produto,40))}</div>
       <div class="detalhe">${brl(f.min)} até ${brl(f.max)} · ${f.n} ofertas</div>
     </div><div class="economia" style="color:var(--vermelho)">${pct(f.cv)}</div></div>`).join("")
    : '<div class="vazio">Nenhum produto com dispersão preocupante.</div>';

  tabela("t-melhor",[
    {titulo:"#",valor:(l,i)=>`<span class="posicao ${i<3?'top':''}">${i+1}</span>`},
    {titulo:"Produto",valor:l=>esc(corta(l.produto,38))},
    {titulo:"Melhor oferta",valor:l=>l.melhor.url
      ? `<a href="${esc(l.melhor.url)}" target="_blank" rel="noopener">${esc(corta(l.melhor.titulo,42))}</a>`
      : esc(corta(l.melhor.titulo,42))},
    {titulo:"Loja",valor:l=>esc(l.melhor.loja||"sem loja")},
    {titulo:"Preço",num:true,valor:l=>`<span class="neg">${brl(l.min)}</span>`},
    {titulo:"vs mediana",num:true,valor:l=>`<span class="neg">${pct((l.min-l.mediana)/l.mediana*100)}</span>`},
  ],[...faixas].sort((a,b)=>b.economia-a.economia));

  // Fabricantes
  const marcas = Object.entries(agrupa(ofertas,o=>o.marca)).map(([marca,itens])=>
    ({marca,...estatistica(itens.map(i=>i.preco))})).sort((a,b)=>b.media-a.media);
  document.getElementById("g-marca").innerHTML =
    barras(marcas.map(m=>({rotulo:m.marca,valor:m.media})),brl,"#4ea3ff");
  tabela("t-marca",[
    {titulo:"Fabricante",valor:l=>esc(l.marca)},
    {titulo:"Ofertas",num:true,valor:l=>l.n},
    {titulo:"Menor",num:true,valor:l=>brl(l.min)},
    {titulo:"Médio",num:true,valor:l=>brl(l.media)},
    {titulo:"Maior",num:true,valor:l=>brl(l.max)},
    {titulo:"Dispersão",num:true,valor:l=>pct(l.cv)},
  ],marcas);

  // Lojas
  const medianaGeral = geral?geral.mediana:0;
  const listaLojas = Object.entries(agrupa(ofertas,o=>o.loja||"Loja não informada"))
    .map(([loja,itens])=>{ const e=estatistica(itens.map(i=>i.preco));
      return {loja,...e,preferida:itens.some(i=>i.loja_preferida),
              vs:medianaGeral?(e.min-medianaGeral)/medianaGeral*100:0}; })
    .sort((a,b)=>(b.preferida?1:0)-(a.preferida?1:0)||b.n-a.n);
  tabela("t-loja",[
    {titulo:"#",valor:(l,i)=>`<span class="posicao ${i<3?'top':''}">${i+1}</span>`},
    {titulo:"Loja",valor:l=>l.preferida
      ? `<span class="preferida">${esc(l.loja)}</span>` : esc(l.loja)},
    {titulo:"Ofertas",num:true,valor:l=>l.n},
    {titulo:"Menor",num:true,valor:l=>brl(l.min)},
    {titulo:"Médio",num:true,valor:l=>brl(l.media)},
    {titulo:"vs mediana",num:true,valor:l=>`<span class="${l.vs<0?'neg':'pos'}">${pct(l.vs)}</span>`},
  ],listaLojas);

  // Dispersão
  const dispersao = faixas.filter(f=>f.n>1).sort((a,b)=>b.cv-a.cv);
  document.getElementById("g-cv").innerHTML = barras(dispersao.slice(0,14).map(d=>({
    rotulo:d.produto, valor:d.cv,
    cor: d.cv>50?"#ff6b7a":d.cv>25?"#ffc861":"#2fd6a0"})),pct,"#4ea3ff");
  tabela("t-estat",[
    {titulo:"Produto",valor:l=>esc(corta(l.produto,38))},
    {titulo:"Ofertas",num:true,valor:l=>l.n},
    {titulo:"25%",num:true,valor:l=>brl(l.p25)},
    {titulo:"Mediana",num:true,valor:l=>brl(l.mediana)},
    {titulo:"75%",num:true,valor:l=>brl(l.p75)},
    {titulo:"Desvio",num:true,valor:l=>brl(l.dp)},
    {titulo:"Dispersão",num:true,valor:l=>`<span class="${l.cv>50?'pos':''}">${pct(l.cv)}</span>`},
  ],dispersao);

  // Ofertas
  document.getElementById("c-ofertas").textContent =
    `${ofertas.length} ofertas no recorte, da mais barata para a mais cara.`;
  tabela("t-ofertas",[
    {titulo:"Produto",valor:o=>esc(corta(o.produto,26))},
    {titulo:"Anúncio",valor:o=>o.url
      ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(corta(o.titulo,44))}</a>`
      : esc(corta(o.titulo,44))},
    {titulo:"Fabricante",valor:o=>esc(o.marca)},
    {titulo:"Loja",valor:o=>o.loja_preferida
      ? `<span class="preferida">${esc(o.loja||"sem loja")}</span>` : esc(o.loja||"sem loja")},
    {titulo:"Status",valor:o=>`<span class="tag ${esc(o.classificacao||"")}">${rotuloClasse(o.classificacao)}</span>`},
    {titulo:"Preço",num:true,valor:o=>`${brl(o.preco)}${marcaAlerta(o)}`},
    {titulo:"vs mediana",num:true,valor:o=>o.desvio_mediana_pct===null
      || o.desvio_mediana_pct===undefined ? "—"
      : `<span class="${o.desvio_mediana_pct>0?'pos':'neg'}">${
          o.desvio_mediana_pct>0?"+":""}${o.desvio_mediana_pct.toFixed(1)}%</span>`},
  ],[...ofertas].sort((a,b)=>a.preco-b.preco).slice(0,500),
    o=>o.alerta_preco?"suspeita":"");

  renderHistorico();
}

function renderHistorico() {
  const h = DADOS.historico || {execucoes:[],series:[],variacoes:[]};
  const alvo = document.getElementById("hist-conteudo");
  if (!h.execucoes.length) {
    alvo.innerHTML = `<div class="bloco largo"><div class="vazio">
      Ainda não há histórico.<br><br>Cada busca grava uma medição deduplicada.
      A partir da segunda coleta em dias diferentes, esta área mostra quanto
      cada produto subiu ou caiu.</div></div>`;
    return;
  }
  if (h.execucoes.length === 1 || !h.variacoes.length) {
    alvo.innerHTML = `<div class="bloco largo"><div class="vazio">
      ${h.execucoes.length} medição(ões) registrada(s), a primeira em
      ${esc(h.execucoes[0].executado_em.slice(0,10))}.<br><br>
      A comparação aparece quando houver medições em dias diferentes.</div></div>`;
    return;
  }
  const subiu = h.variacoes.filter(v=>v.variacao_pct>0);
  const caiu = h.variacoes.filter(v=>v.variacao_pct<0);
  alvo.innerHTML = `
    <div class="cards">
      <div class="card" style="--cor:var(--azul)"><div class="rotulo">Medições</div>
        <div class="valor">${h.execucoes.length}</div>
        <div class="nota">${esc(h.execucoes[0].executado_em.slice(0,10))} até ${esc(h.execucoes.at(-1).executado_em.slice(0,10))}</div></div>
      <div class="card" style="--cor:var(--vermelho)"><div class="rotulo">Subiram</div>
        <div class="valor">${subiu.length}</div><div class="nota">na última comparação</div></div>
      <div class="card" style="--cor:var(--verde)"><div class="rotulo">Caíram</div>
        <div class="valor">${caiu.length}</div><div class="nota">na última comparação</div></div>
    </div>
    <div class="bloco largo"><h2>Variação do menor preço</h2>
      <div class="legenda">Comparação entre as duas últimas medições de cada produto.</div>
      <div class="rolagem"><table id="t-hist"></table></div></div>`;
  tabela("t-hist",[
    {titulo:"Produto",valor:v=>esc(corta(v.produto,42))},
    {titulo:"Anterior",num:true,valor:v=>brl(v.menor_anterior)},
    {titulo:"Atual",num:true,valor:v=>brl(v.menor_atual)},
    {titulo:"Variação",num:true,valor:v=>`<span class="${v.variacao_pct<0?'neg':'pos'}">${pct(v.variacao_pct)}</span>`},
  ],h.variacoes);
}

preencheSelect("f-marca",unicos(DADOS.ofertas,o=>o.marca),"Todos os fabricantes");
preencheSelect("f-produto",unicos(DADOS.ofertas,o=>o.produto),"Todos os produtos");
preencheSelect("f-loja",unicos(DADOS.ofertas,o=>o.loja),"Todas as lojas");
preencheSelect("f-classe",unicos(DADOS.ofertas,o=>o.classificacao),"Todos",rotuloClasse);

const ligacoes = {"f-marca":"marca","f-produto":"produto","f-loja":"loja",
                  "f-classe":"classe","f-alerta":"alerta","f-preco":"preco"};
Object.entries(ligacoes).forEach(([id,campo]) =>
  document.getElementById(id).addEventListener("input",e=>{filtros[campo]=e.target.value;render();}));
document.getElementById("limpar").addEventListener("click",()=>{
  Object.keys(filtros).forEach(k=>filtros[k]="");
  Object.keys(ligacoes).forEach(id=>document.getElementById(id).value="");
  render();
});
document.querySelectorAll(".aba").forEach(aba=>aba.addEventListener("click",()=>{
  document.querySelectorAll(".aba").forEach(a=>a.classList.remove("ativa"));
  aba.classList.add("ativa");
  document.querySelectorAll(".painel").forEach(p=>p.hidden=true);
  document.getElementById(aba.dataset.alvo).hidden=false;
}));

document.getElementById("rodape").textContent = `Atualizado em ${DADOS.gerado_em}`;
document.getElementById("selo").textContent =
  DADOS.origem === "historico acumulado" ? "histórico acumulado" : "última coleta";
render();
</script>
</body>
</html>
"""
