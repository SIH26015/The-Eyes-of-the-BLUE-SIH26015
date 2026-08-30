# Team Ownership

## Module Owners

| Module | Owner | Responsibility |
|--------|-------|---------------|
| Module_0 | Research Team | Study areas, requirements, acquisition planning |
| Module_1 | Frontend Team | UI/UX, map visualization, user interactions |
| Module_2 | Backend Team | API, ingestion, catalog, data pipeline |
| Module_3 | Analysis Team | Terrain, vegetation, spatial analysis |

## Branch Strategy

- `main` — Stable baseline (v0.1.0)
- `restructure/*` — Architecture refactoring branches
- Feature branches: `feature/{module}-{description}`
- Bug fixes: `fix/{module}-{description}`

## Review Process

1. Create feature branch from `main`
2. Implement and test
3. Open PR with description
4. Module owner reviews
5. Merge after approval

## Communication

- Cross-module changes require coordination with affected module owners
- API changes must be reflected in `docs/API_CONTRACT.md`
- Data schema changes must be reflected in `docs/DATA_CONTRACT.md`
