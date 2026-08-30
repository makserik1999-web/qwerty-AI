module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  ignorePatterns: ['dist', 'node_modules', '.eslintrc.cjs', 'vite.config.ts'],
  parser: '@typescript-eslint/parser',
  plugins: ['@typescript-eslint', 'react-hooks'],
  rules: {
    // The one rule set is worth keeping strict: hooks must obey the rules.
    'react-hooks/rules-of-hooks': 'error',
    // Type safety is enforced by tsc (strict + noUnusedLocals); eslint here
    // focuses on hooks correctness and syntax.
    'no-unused-vars': 'off',
    '@typescript-eslint/no-unused-vars': 'off',
  },
};