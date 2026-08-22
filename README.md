# Kan Scrape

Kan Scrape monorepo. The project is organized into independent applications and services that share the same repository.

## Structure

```text
kan-scrape/
├── kan-scrape-front/   # Web application (React + TypeScript + Vite)
└── kan-scrape-back/    # API and backend services (planned)
```

## Local development

### Frontend

```bash
cd kan-scrape-front
pnpm install
pnpm dev
```

Available commands:

```bash
pnpm build
pnpm lint
pnpm preview
```

## Project status

The frontend is the first part of the monorepo. The backend implementation will be added soon.

## Project documentation

- [Design system](./DESIGN.md)
- [Agent instructions](./AGENTS.md)
- [Contributing](./CONTRIBUTING.md)

## License

This project is distributed under the [MIT License](./LICENSE).
