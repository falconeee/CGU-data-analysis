# Análise de Dados — CGU

Detecção de anomalias e indícios de fraude em contratos e licitações públicas, com um
dashboard para visualizar e pesquisar os resultados.

> **Indícios não são prova.** Os scores servem para priorizar análise humana. Cada indício
> vem com a evidência que o gerou.

## Como rodar

Requer Python 3.12+ e [uv](https://docs.astral.sh/uv/).

```bash
uv sync                               # instala dependências
uv run cgu all                        # gera a base sintética, detecta, pontua e valida (~10 s)
uv run streamlit run app/Home.py      # abre o dashboard em http://localhost:8501
uv run pytest                         # testes
```

Por padrão o projeto usa uma **base sintética** gerada localmente: órgãos, municípios,
empresas e pessoas são fictícios, e há fraudes plantadas com gabarito. Os CNPJs sintéticos
são alfanuméricos e começam com `Z`, então não colidem com nenhum CNPJ real numérico. O
dashboard mostra o selo "Dados sintéticos" enquanto essa base estiver carregada.

## Arquitetura

```
fonte (sintética | real) ──> modelo canônico (DuckDB) ──> detectores ──> score ──> validação ──> dashboard
```

As duas fontes produzem as mesmas tabelas (`src/cgu/schema.py`, validadas com pandera):
`agency`, `category`, `supplier`, `partner`, `tender`, `bidder`, `contract`, `item`,
`ref_price` e `sanction`. A base sintética tem ainda a tabela `ground_truth`. Detectores,
score e dashboard não sabem de onde vieram os dados.

| Pasta | Conteúdo |
|---|---|
| `src/cgu/synthetic/` | gerador da base sintética e cenários plantados |
| `src/cgu/ingest/` | clientes das APIs públicas (modo real) |
| `src/cgu/transform/` | staging do modo real → modelo canônico |
| `src/cgu/detectors/` | Isolation Forest, Benford, sobrepreço, grafo/Louvain, red flags |
| `src/cgu/scoring/` | score agregado e validação |
| `app/` | dashboard Streamlit |
| `config.yaml` | fonte, recorte, limiares, pesos e limites de dispensa |

Comandos da CLI: `cgu generate | ingest | build | detect | score | validate | all`.

## Técnicas

| Indício | Como é detectado | Nível |
|---|---|---|
| Contrato atípico | Isolation Forest sobre valor, valor vs categoria, duração, aditivos, nº de licitantes, modalidade, atraso de publicação e idade da empresa | contrato |
| Lei de Benford | 1º e 2º dígitos, χ², MAD com as faixas de Nigrini; mínimo de 100 valores | órgão / fornecedor |
| Sobrepreço | preço unitário > 1,5× a mediana **e** > Q3 + 1,5·IQR da referência por item/UF/ano | item → contrato |
| Possível cartel | grafo de co-participação + sócios em comum, comunidades Louvain, coesão e rodízio de vencedores | comunidade → contrato |
| Sócios em comum entre concorrentes | licitantes da mesma licitação com sócio (nome + CPF mascarado) ou CNPJ básico em comum | licitação → contrato |
| Empresa recém-criada | menos de 365 dias entre a abertura e a assinatura | contrato |
| Fracionamento de despesas | ≥ 3 dispensas do mesmo órgão (mesma categoria ou mesmo fornecedor) em 90 dias, cada uma abaixo do limite do art. 75 da Lei 14.133 e somando acima dele | contrato |
| Fornecedor único recorrente | ≥ 5 contratos no órgão e participação ≥ 15% do valor ou ≥ 80% com licitante único | órgão × fornecedor |

**Score agregado** (por contrato): risco = 1 − ∏(1 − pesoᵢ × scoreᵢ), um noisy-OR. Cada
indício tem um peso de gravidade (`config.yaml`). Um indício forte isolado já eleva o risco,
e indícios independentes se acumulam sem passar de 1. **Por órgão**: risco médio, p90 e
valor ponderado pelo risco (Σ valor × risco).

**Validação**: o CEIS/CNEP entra só como **rótulo**, nunca como entrada dos detectores. O
contrato é positivo quando o fornecedor foi sancionado depois da assinatura. Métricas: AUC,
precisão@k e lift. Na base sintética, cada detector é medido também contra o gabarito do
cenário que deveria encontrar. Relatório em `data/reports/validation.json`.

### Resultado na base sintética (seed 42)

| Cenário plantado | Detector | Recall | Precisão |
|---|---|---|---|
| Cartel (empresas) | Louvain | 1,00 | 1,00 |
| Cartel (licitações) | Sócios em comum | 1,00 | 1,00 |
| Empresa recém-criada | Empresa recém-criada | 1,00 | 0,38 |
| Fracionamento | Fracionamento | 0,84 | 0,46 |
| Sobrepreço (itens) | Sobrepreço | 0,97 | 0,88 |
| Fornecedor único | Fornecedor único | 1,00 | 0,83 |
| Valores fabricados (órgãos) | Benford | 1,00 | 0,40 |
| Contratos atípicos | Isolation Forest | 1,00 | 0,35 |

AUC do score contra o gabarito: 0,97. Contra as sanções sintéticas, que são um rótulo
ruidoso de propósito: 0,69, com lift de 8,6× nos 100 contratos de maior risco.

Os cenários sintéticos são mais "limpos" que a realidade. Esses números mostram que cada
detector encontra o padrão que deveria, não o desempenho esperado em dados reais. Os falsos
positivos têm causas realistas, mantidas de propósito: empresas novas legítimas, órgãos que
compram uma única categoria (o que distorce Benford) e contratos de serviço com muitos
aditivos.

## Modo real (dados públicos)

```bash
cp .env.example .env        # preencha CGU_API_KEY (chave da API do Portal da Transparência)
uv run cgu all --fonte real --amostra                 # 1 mês, para testar
uv run cgu all --fonte real --uf ES --inicio 2024-10-01 --fim 2026-09-30
```

| Fonte | Uso |
|---|---|
| PNCP (`pncp.gov.br/api/consulta` e `/api/pncp`) | contratações por UF, itens, resultados (preço homologado, vencedor) e contratos |
| Portal da Transparência (API, chave) | participantes de licitações federais e CEIS/CNEP |
| Receita Federal (dados abertos do CNPJ) | data de abertura, porte e quadro societário |
| Compras.gov.br (pesquisa de preços) | preço de referência por código de item e UF |

**Volume e tempo** (medido para o ES): ~2 mil contratações por mês. Em 24 meses, o pico de
disco fica em ~4 GB e a RAM abaixo de 4 GB. O gargalo é a coleta nas APIs, da ordem de
10–15 h: a API de contratos não filtra por UF, então leva ~1 min por dia de dados. Por isso:

- tudo passa por **cache em disco**, e rodar de novo retoma de onde parou;
- os resultados por item são coletados só para os 300 códigos mais frequentes e para
  contratações sem contrato publicado (`top_item_codes`);
- o dump do CNPJ é baixado **um ZIP por vez**, lido em streaming, filtrado pelos CNPJs que
  aparecem nos dados e apagado;
- a coleta aborta se houver menos de 5 GB livres (`min_free_disk_gb`).

**Limitações conhecidas do modo real:**

- **URL do dump do CNPJ**: o endereço antigo (`arquivos.receitafederal.gov.br/dados/cnpj/...`)
  retorna 404 e virou um compartilhamento Nextcloud. Preencha `real.cnpj_dump_url` no config.
  Sem ela, os indícios de empresa recém-criada e de sócios em comum ficam vazios.
- **Participantes**: só o Portal publica a lista de licitantes, e só para licitações federais.
  Nos testes (pregões federais do ES em mar/2025) a API retornou listas vazias. Sem
  participantes, o grafo de cartéis e os sócios em comum só enxergam os vencedores.
- **Downloads em lote do Portal** (ZIP) recusaram acesso automatizado (HTTP 403). Por isso
  tudo vem pela API.
- **Código de item**: muitos itens do PNCP vêm sem código CATMAT/CATSER. Sem código não há
  referência de preço, e esses itens ficam fora do sobrepreço.
- **Aditivos** não são coletados (exigiria uma chamada por contrato). O valor final é o maior
  entre valor inicial, global e acumulado.
- **Categoria** vem do contrato (ex.: "Compras", "Serviços de Engenharia"), que é grossa. O
  fracionamento por "mesmo fornecedor" é o critério mais preciso.
- **Limites de dispensa** de 2026 repetem os de 2025 até a conferência do decreto.
- **CNPJ alfanumérico**: tratado como texto `[A-Z0-9]{12}` + 2 DVs em todo o pipeline.

## Viés do rótulo de sanções

Sanção depende de fiscalização, denúncia e processo, não só de fraude. Órgãos mais
fiscalizados geram mais sanções, e muita fraude nunca é sancionada. AUC e precisão contra o
CEIS/CNEP medem concordância com esse rótulo imperfeito, não a taxa real de acerto.
