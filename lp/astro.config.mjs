import { defineConfig } from 'astro/config';
import tailwind from '@astrojs/tailwind';

export default defineConfig({
  site: 'https://salesanchor.jp',
  integrations: [
    tailwind({
      applyBaseStyles: false,
    }),
  ],
  // build.format はデフォルト 'directory' のまま（dist/privacy/index.html）
  // 既存 nginx の try_files ルール（PR #172, #184）と整合させ、
  // /privacy /terms /data-deletion のクリーンURLを 200 で返すため
});
