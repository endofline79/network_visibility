# Asset and dependency credits

- The locally bundled country vector map uses `@d3-maps/atlas` 1.0.1 (MIT, Copyright 2026 Georgii Bukharov) and its Natural Earth public-domain 110m country data. Package license is retained in `frontend/public/assets/atlas-LICENSE.txt`. Map geometry is bundled into the app; no tile service receives any endpoint or location data.

- React, Vite, TypeScript, d3-geo and their transitive packages: licenses distributed with npm packages; exact versions in package-lock.json. Lucide icons: ISC license. Existing repo dependency pins retained.
- Optional local DB-IP Lite MMDB: CC BY 4.0; https://db-ip.com/db/lite.php . Attribution appears in the application. Database is not bundled; mount the existing public-data directory read-only. Locations are approximate and database age is exposed.
- `backend/filterlog.py`: reused from this Visibility repository; it has no collector startup code.
