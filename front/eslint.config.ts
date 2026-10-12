import { globalIgnores } from 'eslint/config'
import { defineConfigWithVueTs, vueTsConfigs } from '@vue/eslint-config-typescript'
import pluginVue from 'eslint-plugin-vue'
import pluginPlaywright from 'eslint-plugin-playwright'
import pluginVitest from '@vitest/eslint-plugin'
import pluginOxlint from 'eslint-plugin-oxlint'
import skipFormatting from 'eslint-config-prettier/flat'

// To allow more languages other than `ts` in `.vue` files, uncomment the following lines:
// import { configureVueProject } from '@vue/eslint-config-typescript'
// configureVueProject({ scriptLangs: ['ts', 'tsx'] })
// More info at https://github.com/vuejs/eslint-config-typescript/#advanced-setup

export default defineConfigWithVueTs(
  {
    name: 'app/files-to-lint',
    files: ['**/*.{vue,ts,mts,tsx}'],
  },

  // dist-electron 是构建产物（esbuild 打包出来的 .cjs），不该被 lint ——
  // 它会报 no-require-imports 之类的误报。
  globalIgnores(['**/dist/**', '**/dist-ssr/**', '**/dist-electron/**', '**/coverage/**']),

  ...pluginVue.configs['flat/essential'],
  vueTsConfigs.recommended,

  {
    // src/views/** 是路由组件，天然就是单词名（Chat.vue / AdminView.vue 里的 Chat 等）。
    // 给它们关掉 multi-word-component-names，比为了过规则改名（会牵动 router 与测试）更划算。
    name: 'app/views-single-word-names',
    files: ['src/views/**/*.vue'],
    rules: {
      'vue/multi-word-component-names': 'off',
    },
  },

  {
    // 下划线前缀 = 「这个参数/变量是故意不用的」。
    // 不加这条配置的话，规则会一边提示「Unused parameters should start with a '_'」，
    // 一边继续报 `_delta` 未使用 —— 那就只能删参数或改调用点，反而更糟。
    name: 'app/underscore-ignores-unused',
    files: ['**/*.{vue,ts,mts,tsx}'],
    rules: {
      '@typescript-eslint/no-unused-vars': [
        'error',
        {
          argsIgnorePattern: '^_',
          varsIgnorePattern: '^_',
          caughtErrorsIgnorePattern: '^_',
        },
      ],
    },
  },

  {
    ...pluginPlaywright.configs['flat/recommended'],
    files: ['e2e/**/*.{test,spec}.{js,ts,jsx,tsx}'],
    rules: {
      // 这三条与本项目的 E2E 约定直接冲突，**刻意关掉**（不是图省事）：
      // - no-skipped-test / no-conditional-in-test：CI 里**没有后端进程**，
      //   所以「后端不可用就 test.skip」是硬要求 —— 否则 E2E 在 CI 必然全红。
      // - no-wait-for-timeout：3D（WebGL 首帧）与音频（decodeAudioData）需要等真实时间，
      //   没有可轮询的 DOM 信号。
      ...pluginPlaywright.configs['flat/recommended'].rules,
      'playwright/no-skipped-test': 'off',
      'playwright/no-conditional-in-test': 'off',
      'playwright/no-wait-for-timeout': 'off',
    },
  },

  {
    ...pluginVitest.configs.recommended,
    files: ['src/**/__tests__/*'],
  },

  ...pluginOxlint.buildFromOxlintConfigFile('.oxlintrc.json'),

  skipFormatting,
)
