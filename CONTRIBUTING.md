# Contributing

Kan Scrape is maintained for Kyoto Tech Meetup. Contributions are limited to members of the [`kyoto-tech`](https://github.com/kyoto-tech) GitHub organization.

If you are not a member of the organization, please do not open a pull request. Contact the maintainers if you believe you should have access.

## Before making changes

- Confirm that you are a member of the `kyoto-tech` GitHub organization.
- Read [`AGENTS.md`](./AGENTS.md) for repository-specific instructions.
- Read [`DESIGN.md`](./DESIGN.md) before changing visual behavior or shared tokens.
- Keep the scope focused and preserve unrelated work.

## Frontend changes

From `kan-scrape-front/`:

```bash
pnpm install
pnpm lint
pnpm build
```

When changing UI:

- Use the documented Kyoto Tech Meetup tokens and patterns.
- Keep semantic HTML, keyboard behavior, focus states, and touch targets correct.
- Check English and Japanese text lengths where content is user-provided.
- Update documentation when a shared design or architecture decision changes.

## Pull requests

Only members of the `kyoto-tech` GitHub organization may submit pull requests.

Keep pull requests focused and describe:

- What changed and why.
- Which app, components, or documentation were affected.
- Which checks were run.
- Any visual, accessibility, bilingual-content, or API considerations reviewers should verify.
