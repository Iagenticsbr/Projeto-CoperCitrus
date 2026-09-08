# Integração com o Mercado Livre

Tudo o que o projeto usa para falar com o Mercado Livre. Nenhum segredo está
aqui: token, `CLIENT_SECRET` e senhas ficam em variável de ambiente.

## Aplicação

| item | valor |
|---|---|
| `CLIENT_ID` | `994633731209600` |
| `CLIENT_SECRET` | variável `ML_CLIENT_SECRET` (nunca no repositório) |
| `REDIRECT_URI` | `https://iagentics.com.br/academy` |
| Escopo necessário | `offline_access read` |

O `REDIRECT_URI` precisa estar cadastrado igual no painel de aplicações do
Mercado Livre, caractere por caractere, senão a troca do código falha.

## Autorização

Passo 1 — a pessoa abre no navegador e autoriza:

```
https://auth.mercadolivre.com.br/authorization?response_type=code&client_id=994633731209600&redirect_uri=https%3A%2F%2Fiagentics.com.br%2Facademy&scope=offline_access+read
```

`offline_access` não é opcional. Sem ele o Mercado Livre devolve token e
**não** devolve `refresh_token`, e a coleta mensal quebra na segunda execução
sem ninguém na frente da tela para reautorizar.

Passo 2 — o navegador volta com `?code=TG-...`. Esse código vira token:

```
POST https://api.mercadolibre.com/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=authorization_code
client_id=...&client_secret=...&code=TG-...&redirect_uri=...
```

Passo 3 — renovação, quando existe `refresh_token`:

```
POST https://api.mercadolibre.com/oauth/token
grant_type=refresh_token&client_id=...&client_secret=...&refresh_token=...
```

O token vive 6 horas. O projeto renova com **5**, uma hora antes de vencer:
uma coleta longa pode começar com o token quase vencido e terminar depois do
prazo. Implementado em `src/copercitrus_price_collector/ml_token.py`.

## Endpoints usados na coleta

Base `https://api.mercadolibre.com`, sempre com o cabeçalho
`Authorization: Bearer <token>`.

| chamada | para quê |
|---|---|
| `GET /products/search?status=active&site_id=MLB&q=<termos>` | acha o produto no catálogo |
| `GET /products/{id}/items?limit=10` | **as ofertas com preço** daquele produto |
| `GET /products/{id}` | nome, marca e modelo do catálogo — usado também para conferir link |

A busca é feita em **cascata**, da consulta mais específica para a mais ampla,
porque o catálogo pondera o texto inteiro e a descrição completa da planilha
afoga o código do modelo:

1. o código isolado — `IM125`, `CIV200B`, `DWE4120B2B`
2. código + marca — `CIV200B Vonder`
3. a descrição completa da planilha
4. função + marca — `lavadora alta pressao Jacto`

Os candidatos de todas as consultas são reunidos, pontuados e só então os 8
melhores têm o preço buscado. Cada produto custa uma chamada extra.

## Endpoints de tendência

Funcionam com o mesmo token e não custam nada.

| chamada | devolve |
|---|---|
| `GET /trends/MLB/{categoria}` | 50 termos mais buscados da categoria |
| `GET /highlights/MLB/category/{categoria}` | 20 mais vendidos (ids de produto) |
| `GET /categories/{id}` | nome e total de anúncios da categoria |
| `GET /sites/MLB/categories` | as 32 categorias raiz |

Categorias que interessam a esta base: `MLB263532` Ferramentas, `MLB271599`
Agro, `MLB1500` Construção, `MLB1499` Indústria e Comércio.

## O que responde 403 para esta aplicação

Sem parceria aprovada, estes não abrem — e é por isso que a coleta passa pelo
catálogo em vez de pela busca de anúncios:

- `GET /sites/MLB/search` — seria o caminho óbvio, e o único que traz
  `sold_quantity`
- `GET /items/{id}` e `GET /items?ids=` — detalhe do anúncio
- `GET /reviews/item/{id}` — avaliações
- `?catalog_product_id=` na busca de anúncios

Consequência prática: **não há como saber quantas unidades um anúncio vendeu,
nem histórico de preço**. O histórico quem constrói é este projeto, medindo
mês a mês.

## Limitações medidas

**O catálogo não cobre tudo.** Produto vendido só como anúncio avulso, nunca
vinculado a um produto de catálogo, não aparece em `/products/search`. Parte
da linha a bateria da Vonder está nessa situação.

**A busca não é determinística.** Duas chamadas seguidas de
`/products/search` com a mesma consulta devolvem conjuntos diferentes. Como o
histórico acumula e deduplica, execuções mensais aumentam a cobertura em vez
de sobrescrever.

**O anúncio individual não tem permalink na resposta.** O endereço é montado
como `https://www.mercadolivre.com.br/p/{product_id}` — a página do produto no
catálogo, que é exatamente o produto cujo nome aparece no painel. Não se
inventa formato de URL.

## Configuração

| variável | uso |
|---|---|
| `ML_TOKEN` | token pronto; tem precedência sobre o arquivo |
| `ML_CLIENT_ID` / `ML_CLIENT_SECRET` | necessários para renovar |

```bash
copercitrus-price collect planilha.xlsx \
  --providers mercadolivre \
  --incluir-similares \
  --limit 20 --delay 1 --similaridade-minima 70
```

`--ml-token-arquivo` aponta o JSON com o par de tokens, renovado sozinho.

## Arquivos

| arquivo | responsabilidade |
|---|---|
| `providers/mercadolivre_oficial.py` | consultas, cascata, ofertas, montagem do link |
| `ml_token.py` | autorização, troca do código, renovação com 5 horas |
| `product_analysis.py` | pontuação e classificação em exato / similar / divergente |
