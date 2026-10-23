# Auditoria: Radar de máquinas v1.3.0

Data: 23/10/2026.

## Base e candidato

A base é a tag `v1.0.1`. O candidato é o commit desta release na `main`, que vem depois de `ccb2961`, `2ab2e38` (1.1.0), `f369d20` e `30fe819` (1.1.1), `057286b` (1.2.0) e `a0867a1` (1.3.0). Não havia branches, PRs nem worktrees a integrar.

## Matriz de evidências

| Resultado | Evidência | Validação |
| --- | --- | --- |
| Soma de CPU, RAM e disco com folga | MachinesModel.js `capacity`, `amount`; `buildMachines().capacity` | Teste Node da soma: Railway, celular e desligada ficam fora; disco com imagem reservada não conta em dobro; histórico pesado pelo tamanho |
| Aba Total | Content.qml `totalView`, aba `total` | Renderizada numa bancada com o estado real e com o anonimizado |
| Folga só nas nossas | `capacity().free`, `freeText` | Bancada: 4 máquinas sem `readonly` somadas à parte |
| Soma pros agentes | skill `radar-maquinas`, `maquinas.py --total` | Mesmo estado: 36% de CPU, 37% de RAM e 62% de disco no script e no painel |
| Swarm e Railway por API | cloud.py `portainer_probe`, `railway_probe`; collect.py `api_kind` | Testes Python `CloudTests`; coleta real dos 4 nós e da conta Railway |
| Chip de cluster | MachinesModel.js `groupRows`; Content.qml `groupTab` | Teste Node; bancada com o chip aberto |
| Ações, celular e readonly (1.1.0) | act.py, android.py, Content.qml | Testes Python e Node; bancada |
| Swap por pressão (1.1.1) | probe.py PSI; MachinesModel.js `swapTone` | Testes Node de swap cheia e quieta, com pressão e sem PSI |

## Validações

- `node --test tests/test_model.cjs`: 18 testes passaram.
- `python3 -m unittest discover -s tests`: 13 testes passaram.
- `omarchy-plugin-validate .`: passou.
- `python3 install.py` publicou a nova geração, e o IPC `diagnostics` da barra devolveu `version: "1.3.0"`.

## Agentes e sessões

- Claude Code (Opus 5.5), sessão `564c0d1b-6633-445c-8e30-158fe308b0d6`.

## Pendências

Nenhuma.
