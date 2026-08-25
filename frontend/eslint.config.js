const jsxUsesVars = {
  meta: { schema: [] },
  create(context) {
    return {
      JSXOpeningElement(node) {
        const root = node.name.type === "JSXMemberExpression" ? node.name.object : node.name;
        if (root.type === "JSXIdentifier") context.sourceCode.markVariableAsUsed(root.name, node);
      },
    };
  },
};

export default [
  {
    files: ["src/**/*.{js,jsx}"],
    languageOptions: {
      ecmaVersion: "latest",
      sourceType: "module",
      parserOptions: { ecmaFeatures: { jsx: true } },
    },
    plugins: { local: { rules: { "jsx-uses-vars": jsxUsesVars } } },
    rules: {
      "local/jsx-uses-vars": "error",
      "no-unused-vars": ["error", { argsIgnorePattern: "^_", varsIgnorePattern: "^_" }],
    },
  },
];
