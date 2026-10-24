# Presentation deploy

This checkout builds `visibility-console:0.3.0` for Ops Home. The console image
deployed for tiered alerting is `visibility-console:0.2.0` until that container
is recreated. The image before alerting is
`visibility-console:layout-19604db9bdbf`.

`compose.live.yaml` stays on the host at
`/home/klab/.local/share/visibility/presentation-deploy/compose.live.yaml`.
It names the image and the live mounts. It has no `build:` key, so
`docker compose up --build` against that file does not compile a console image.
Credential paths in that file stay on the host and are not copied into Git.

## Build the tag from this checkout

The source tree is `presentation/` in the git checkout
(`/home/klab/codex/Visibility/presentation`): Dockerfile, `backend/`,
`frontend/`, and `requirements*.txt`. That tree is not inside
`presentation-deploy/`. `PRESENTATION_SOURCE` overrides the path when the
checkout lives somewhere else.

From the checkout:

```bash
docker compose -f compose.presentation.yaml build console
```

The same tag from this directory, using the AI-02 checkout path:

```bash
docker compose -f presentation-deploy/compose.build.yaml build console
```

Either command only builds. It does not recreate the live container. After the
image exists, set the host file's console image to `visibility-console:0.3.0`
and recreate the console without `--build`, as [alerting](../docs/alerting.md)
describes for the previous console image. To roll Ops Home back, point that
same image line at `visibility-console:0.2.0`. The image before alerting
remains `visibility-console:layout-19604db9bdbf`.
