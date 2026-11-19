import parser from "@typescript-eslint/parser";
import hooks from "eslint-plugin-react-hooks";

export default [{
  files: ["src/**/*.{ts,tsx}"],
  languageOptions: { parser, parserOptions: { ecmaVersion: "latest", sourceType: "module", ecmaFeatures: { jsx: true } } },
  plugins: { "react-hooks": hooks },
  rules: {
    "no-debugger": "error",
    "no-dupe-args": "error",
    "no-dupe-else-if": "error",
    "no-duplicate-case": "error",
    "no-unreachable": "error",
    "valid-typeof": "error",
    "react-hooks/rules-of-hooks": "error",
  },
}];
