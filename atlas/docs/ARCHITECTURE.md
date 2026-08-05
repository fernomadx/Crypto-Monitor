# ATLAS Architecture

```
collectors → features → specialists → council → persistence → reports
                              ↓
                         evaluation (offline)
                              ↓
                    investigation queue (future)
```

## Separação

| Camada | Pacote |
|--------|--------|
| Coleta | `app/collectors` |
| Features | `app/features` |
| Especialistas | `app/specialists` |
| Agregação | `app/council` |
| Persistência | `app/models`, `app/database` |
| Avaliação | `app/evaluation` |
| Apresentação | `app/reports`, `app/api` |
| Replay | `app/replay` |

## Contratos

Todo especialista retorna `SpecialistAssessment` (Pydantic).
O Council retorna `CouncilDecision` e **grava antes** de qualquer avaliação de resultado.
