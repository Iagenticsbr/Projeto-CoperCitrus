# Projeto CoperCitrus — RPA de pesquisa de preços

Aplicacao Python que le uma lista de produtos em Excel, abre um Chromium controlado pelo Playwright e pesquisa diretamente nas paginas publicas de comparadores e buscadores de compras.

Nao utiliza SerpAPI, API de Afiliados da Shopee nem qualquer outra API de resultados.

## Fontes disponiveis

| Fonte | `--providers` | Situacao |
|---|---|---|
| Buscape | `buscape` | Coleta normalmente |
| Zoom | `zoom` | Coleta normalmente |
| Bing Shopping | `bing` | Coleta normalmente, unica que expoe a loja vendedora |
| Google Shopping | `google` | Responde com CAPTCHA (`/sorry/index`) para acesso automatizado |
| Shopee | `shopee` | Le a API JSON da propria busca; exige sessao autenticada |

O padrao e `buscape,zoom,bing`. Google e Shopee continuam implementados e sao
selecionaveis, mas hoje bloqueiam a coleta; quando bloqueiam, o RPA registra o
erro na linha e segue o lote em vez de mascarar como "sem resultado".

Os comparadores tambem recusam o Chromium **headless**, entao o padrao passou a
ser janela visivel. O RPA nao falsifica user agent para contornar isso.

## O que o RPA entrega

Cada execucao grava tres artefatos:

- `resultados/precos_retail.xlsx` — relatorio de leitura humana;
- `resultados/precos.db` — SQLite com `produtos`, `ofertas` e `resumo_precos`, base do dashboard;
- `resultados/csv/ofertas.csv` e `resultados/csv/resumo_precos.csv` — mesmo conteudo para BI que nao le SQLite.

O Excel de saida possui tres abas:

- `Resultados`: todos os anuncios encontrados, com preco, marca, nome, quantidade/embalagem, loja, link e classificacao;
- `Produtos similares`: alternativas com similaridade intermediaria em relacao ao produto solicitado;
- `Resumo`: total de ofertas, produtos compativeis, similares e menor preco por item.

### Campos principais

| Campo | Origem |
|---|---|
| Produto solicitado | Planilha de entrada |
| Quantidade solicitada | Planilha de entrada |
| Nome encontrado | Card visivel no marketplace |
| Marca encontrada | Validada no titulo do anuncio |
| Quantidade/embalagem | Extraida de textos como `10 un`, `500 ml` ou `2 kg` |
| Preco | Card visivel no marketplace |
| Similaridade | Comparacao entre produto, marca, modelo e anuncio |
| Link de compra | Link presente no card |

`Quantidade solicitada` representa quanto a CoperCitrus pretende comprar. `Quantidade/embalagem encontrada` representa o volume identificado no anuncio. O RPA nao inventa estoque quando o site nao exibe essa informacao.

## Planilha de entrada

| Coluna | Obrigatoria | Uso |
|---|---:|---|
| `Produto` | Sim | Nome principal da pesquisa |
| `Marca` | Nao | Refina a busca e a validacao |
| `Modelo` | Nao | Refina a busca e a validacao |
| `SKU` | Nao | Mantem rastreabilidade |
| `Quantidade` | Nao | Quantidade solicitada para compra |

Tambem sao reconhecidos cabecalhos como `Nome`, `Item`, `Codigo`, `Qtd` e `Qtde`.

## Instalacao no Windows 11 / Git Bash

Requisitos: Python 3.12+ e Git Bash.

```bash
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -e .
python -m playwright install chromium
cp .env.example .env
```

O arquivo `.env` serve como referencia. As configuracoes podem ser exportadas no terminal; nenhuma credencial e necessaria.

## Uso

Crie uma planilha-modelo:

```bash
copercitrus-price template produtos.xlsx
```

Execucao completa (janela visivel, que e o padrao):

```bash
copercitrus-price collect produtos.xlsx --output resultados/precos.xlsx --database resultados/precos.db --csv-dir resultados/csv
```

Teste curto:

```bash
copercitrus-price collect produtos.xlsx --limit 3
```

Somente uma fonte:

```bash
copercitrus-price collect produtos.xlsx --providers buscape
copercitrus-price collect produtos.xlsx --providers bing
```

Para usar o Chrome ou Edge instalado:

```bash
copercitrus-price collect produtos.xlsx --headed --browser-channel chrome
copercitrus-price collect produtos.xlsx --headed --browser-channel msedge
```

## Shopee: sessao e API da propria pagina

A Shopee nao e raspada por HTML. O RPA abre a busca e chama o endpoint que a
propria vitrine consome (`/api/v4/search/search_items`) com `fetch` de mesma
origem e a sessao do navegador. Nao ha seletor para quebrar quando o site muda
de layout, e a resposta ja traz faixa de preco, volume de vendas e avaliacao.

A busca e por palavra-chave montada a partir da planilha, nao por link de loja.

A fonte exige sessao autenticada. Ha dois caminhos, e os dois deixam a
credencial com voce — o RPA nunca digita, le ou guarda senha:

```bash
# 1. Exportar cookies do seu Chrome (extensao Cookie-Editor, Export as JSON)
copercitrus-price collect produtos.xlsx --providers shopee --cookies cookies_shopee.json

# 2. Ou entrar na conta na janela do proprio RPA e salvar a sessao
copercitrus-price login shopee --storage-state resultados/sessao_shopee.json
copercitrus-price collect produtos.xlsx --providers shopee --storage-state resultados/sessao_shopee.json
```

`--storage-state` regrava a sessao ao fim de cada execucao e tambem no instante
em que uma verificacao e concluida, para que uma falha adiante nao custe o
desafio recem resolvido.

Cookies de sessao equivalem a estar logado: `cookies*.json` e `sessao_*.json`
estao no `.gitignore` e nao devem ser enviados por e-mail, zip ou repositorio.

## Verificacao humana

Quando a fonte apresenta CAPTCHA, o RPA traz a janela para frente, avisa no
log e observa a pagina a cada 3s ate `--manual-verification-seconds`. Quem
resolve o desafio e a pessoa; o RPA apenas percebe que liberou, recarrega a URL
correta e retoma. Ele nao resolve, nao contorna e nao repete a tentativa
quando a fonte responde que a verificacao falhou e mandou voltar mais tarde.

## Acompanhar a execucao

Cada consulta imprime uma linha com posicao, fonte, consulta e o que voltou:

```
[3/20] produto 2/10 | Shopee | LAVADORA ALTA PRESSAO J6600 220V 1350780 JACTO
        6 ofertas | R$ 959,00 a R$ 5.530,74
```

Use `python -u` e redirecione para um arquivo para acompanhar com `tail -f`.
`--debug-dump-dir` salva HTML, URL e captura da tela quando nenhuma oferta e
reconhecida, para distinguir pagina vazia de seletor desatualizado.

## Aplicacao web e dashboard

```bash
pip install -e .[web]
copercitrus-web            # http://localhost:8000
```

| Rota | Uso |
|---|---|
| `/` | envio da planilha e acompanhamento da busca |
| `/dashboard` | painel interativo |
| `/planilha/{id}` | download da planilha final |
| `POST /ingest` | recebe coleta feita em outra maquina |
| `/saude` | verificacao usada pelo Railway |

Sem servidor, o painel tambem sai como arquivo:

```bash
copercitrus-price dashboard --database resultados/precos.db --output resultados/dashboard.html
```

O painel tem seis abas — visao geral, fabricante, loja, dispersao, ofertas e
evolucao — com filtro por fabricante, produto, loja, fonte, classificacao e
teto de preco. E um HTML unico, sem dependencia externa: abre offline e pode
ser enviado por e-mail.

## Railway

Coleta e painel rodam em lugares diferentes, e essa separacao e deliberada:
as fontes recusam navegador headless e a verificacao humana exige alguem na
frente da tela. Um servidor nao tem nenhum dos dois.

- **Railway**: painel, envio de planilha e base historica (`Dockerfile.web`,
  sem navegador).
- **Maquina do operador**: coleta, com sessao valida.

```bash
# no servidor: defina RPA_DATA_DIR (volume) e RPA_INGEST_TOKEN
# na maquina do operador, apos coletar:
copercitrus-price publicar https://SEU-APP.up.railway.app   --database resultados/precos.db --token SEU_TOKEN
```

O deploy usa `railway.json` com `Dockerfile.web` e healthcheck em `/saude`.
Monte um volume em `RPA_DATA_DIR` (padrao `/dados`), senao o historico se
perde a cada deploy.

## Deduplicacao

O historico tem indice unico em `(dia, sku, fonte, loja, titulo, preco)` e
grava com `INSERT OR IGNORE`. Repetir a mesma busca no mesmo dia atualiza o
painel sem duplicar linha; no dia seguinte a mesma oferta entra como nova
medicao, que e o que forma a serie historica. A estatistica diaria e
substituida, nao acumulada — uma medicao por produto por dia.

## Base de dados para o dashboard

```
produtos(sku, produto, marca, modelo, quantidade_solicitada, consulta, linha_origem)
ofertas(id, sku, produto, fonte, posicao, titulo, marca_encontrada, embalagem,
        preco, moeda, loja, url, imagem, similaridade, classificacao,
        status, erro, coletado_em)
resumo_precos(sku, produto, marca, ofertas, ofertas_relevantes, compativeis,
              similares, menor_preco, maior_preco, preco_medio,
              amplitude_percentual, menor_preco_geral, maior_preco_geral,
              fonte_menor_preco, url_menor_preco, fonte_maior_preco,
              url_maior_preco, fontes_consultadas, coletado_em)
```

`menor_preco` e `maior_preco` consideram somente ofertas `COMPATIVEL` ou
`SIMILAR`. `menor_preco_geral` e `maior_preco_geral` mantem a faixa bruta, com
pecas e acessorios — sem essa separacao uma gaxeta de R$ 25,90 aparecia como o
menor preco de um pulverizador.

Cada execucao recria o banco. Para manter historico, aponte `--database` para um
arquivo por data.

## Consulta enviada ao marketplace

A consulta nao usa o codigo de material interno da CoperCitrus: e um codigo de
cadastro proprio, inexistente em anuncio publico, e derrubava a pesquisa. Entram
a descricao, a marca e o numero de peca do fabricante. Abreviacoes de retail
(`DIG`, `AUT`, `JG`) sao expandidas e tags de fornecedor (`VD`) sao removidas.

## Classificacao dos resultados

- `COMPATIVEL`: similaridade de 80% ou mais;
- `SIMILAR`: similaridade entre 50% e 79,9%;
- `DIVERGENTE`: similaridade abaixo de 50%.

A similaridade mede **cobertura**: quanto do item pedido aparece no titulo do
anuncio. Titulo longo de marketplace nao e penalizado por ser longo. Codigo
alfanumerico do modelo (`IM125`, `J6600`, `DWE4120B2B`) presente no anuncio vale
bonus, porque e o sinal mais forte de que se trata do mesmo item e nao de um
parente dele. A aba `Produtos similares` contem somente os resultados
classificados como `SIMILAR`.

## Bloqueios e mudancas de pagina

O RPA usa seletores alternativos porque o HTML dos marketplaces pode mudar. Caso detecte CAPTCHA, trafego incomum, verificacao humana ou acesso negado, a fonte e registrada como erro e o lote continua.

O projeto nao tenta:

- resolver ou contornar CAPTCHA;
- usar modo stealth, proxies rotativos ou falsificacao de identidade;
- acessar paginas autenticadas;
- extrair dados que nao estejam visiveis ao usuario.

## Docker

O container roda o Chromium em modo janela dentro de um display virtual
(Xvfb). Rodar headless no container devolve zero resultado: os comparadores
recusam o Chromium headless.

O container usa a CPU e o IP da maquina que o hospeda. Ele isola a execucao e
torna o lote reprodutivel e agendavel; ele nao transfere o processamento para
outro lugar.

```bash
mkdir -p dados
cp "10 principais skus de retail.xlsx" dados/produtos.xlsx
docker compose run --rm rpa
```

Sem compose:

```bash
docker build -t copercitrus-rpa .
docker run --rm --ipc=host -v "$PWD/dados:/dados" copercitrus-rpa   collect /dados/produtos.xlsx   --output /dados/precos_retail.xlsx   --database /dados/precos.db   --csv-dir /dados/csv
```

`--ipc=host` e obrigatorio: com os 64MB de memoria compartilhada padrao do
Docker a aba do Chromium morre no meio do lote.

O modo de verificacao manual de CAPTCHA nao funciona no container — ninguem ve
a tela para resolver. Para Google e Shopee, use a execucao local com
`--browser-user-data-dir`.

## Testes

Os testes usam cards simulados e nao acessam Google ou Shopee.

```bash
python -m unittest discover -s tests -v
```

## Uso responsavel

Automacao de sites deve ser executada somente quando houver autorizacao e de acordo com os termos e instrucoes automatizadas de cada pagina. Os termos atuais do Google restringem acesso automatizado que contrarie instrucoes legiveis por maquina. Antes de colocar o lote em producao, valide a permissao de uso com o responsavel juridico/contratual e mantenha intervalos conservadores entre pesquisas.
