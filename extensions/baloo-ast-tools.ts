import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { Type } from "typebox";
import { registerDynamicLanguage, parse, Lang, type SgNode } from "@ast-grep/napi";
import python from "@ast-grep/lang-python";
import go from "@ast-grep/lang-go";
import * as fs from "node:fs";
import * as path from "node:path";

// ---------------------------------------------------------------------------
// Language registration — Python and Go are dynamic; TS/JS are built-in.
// ---------------------------------------------------------------------------
registerDynamicLanguage({ python, go });

// ---------------------------------------------------------------------------
// Language detection
// ---------------------------------------------------------------------------

type LangId = Lang | string;

const LANG_EXTS: Record<string, string[]> = {
  python: [".py", ".pyi"],
  typescript: [".ts"],
  tsx: [".tsx"],
  javascript: [".js", ".jsx"],
  go: [".go"],
};

const EXT_TO_LANG: Record<string, LangId> = {
  ".py": "python",
  ".pyi": "python",
  ".ts": Lang.TypeScript,
  ".tsx": Lang.Tsx,
  ".js": Lang.JavaScript,
  ".jsx": Lang.JavaScript,
  ".go": "go",
};

export function detectLanguage(filePath: string): LangId | null {
  const ext = path.extname(filePath).toLowerCase();
  return EXT_TO_LANG[ext] ?? null;
}

// ---------------------------------------------------------------------------
// File reading helper
// ---------------------------------------------------------------------------

export function readFileText(filePath: string): string | null {
  try {
    return fs.readFileSync(filePath, "utf-8");
  } catch (err) {
    console.error(`[ast-tools] Failed to read ${filePath}: ${err}`);
    return null;
  }
}

// ---------------------------------------------------------------------------
// Symbol node kinds per language
// ---------------------------------------------------------------------------

const SYMBOL_KINDS: Record<string, string[]> = {
  python: ["function_definition", "class_definition", "decorated_definition"],
  [Lang.TypeScript]: [
    "function_declaration",
    "class_declaration",
    "method_definition",
    "arrow_function",
    "interface_declaration",
    "type_alias_declaration",
  ],
  [Lang.Tsx]: [
    "function_declaration",
    "class_declaration",
    "method_definition",
    "arrow_function",
    "interface_declaration",
    "type_alias_declaration",
  ],
  [Lang.JavaScript]: [
    "function_declaration",
    "class_declaration",
    "method_definition",
    "arrow_function",
  ],
  go: [
    "function_declaration",
    "method_declaration",
    "type_declaration",
    "type_spec",
  ],
};

// Node kinds that carry a symbol name.
const NAME_KINDS = new Set([
  "identifier",
  "name",
  "property_identifier",
  "type_identifier",
]);

// ---------------------------------------------------------------------------
// Symbol extraction
// ---------------------------------------------------------------------------

export interface SymbolInfo {
  kind: string;
  name: string;
  startLine: number; // 1-indexed
  endLine: number; // 1-indexed
  children: SymbolInfo[];
}

/**
 * Walk the AST and collect symbol definitions up to `maxDepth` levels deep.
 */
function walkSymbols(
  node: SgNode,
  lang: string,
  depth: number,
  maxDepth: number,
): SymbolInfo[] {
  if (depth > maxDepth) return [];

  const kindsList = SYMBOL_KINDS[lang];
  if (!kindsList) return [];

  const symbols: SymbolInfo[] = [];

  for (const child of node.children()) {
    const k = child.kind() as string;

    if (!kindsList.includes(k)) {
      // Not a symbol node — but recurse into it because symbols may be nested
      // (e.g. inside module bodies, namespace blocks, etc.)
      const nested = walkSymbols(child, lang, depth, maxDepth);
      symbols.push(...nested);
      continue;
    }

    // Handle Python decorated_definition: the actual def/class is inside.
    if (k === "decorated_definition") {
      const inner = findInnerDefinition(child, lang);
      if (inner) {
        const range = child.range();
        const sym: SymbolInfo = {
          kind: inner.kind() as string,
          name: extractName(inner),
          startLine: range.start.line + 1,
          endLine: range.end.line + 1,
          children: walkSymbols(inner, lang, depth + 1, maxDepth),
        };
        symbols.push(sym);
      }
      continue;
    }

    const range = child.range();
    const sym: SymbolInfo = {
      kind: k,
      name: extractName(child),
      startLine: range.start.line + 1,
      endLine: range.end.line + 1,
      children: walkSymbols(child, lang, depth + 1, maxDepth),
    };
    symbols.push(sym);
  }

  return symbols;
}

/**
 * For a `decorated_definition` node, find the inner function/class definition.
 */
function findInnerDefinition(
  node: SgNode,
  lang: string,
): SgNode | null {
  const kindsList = SYMBOL_KINDS[lang];
  if (!kindsList) return null;
  for (const child of node.children()) {
    const k = child.kind() as string;
    if (k !== "decorated_definition" && kindsList.includes(k)) {
      return child;
    }
  }
  return null;
}

/**
 * Extract the name of a symbol node by looking for name-bearing child nodes.
 */
function extractName(node: SgNode): string {
  for (const child of node.children()) {
    if (NAME_KINDS.has(child.kind() as string)) {
      return child.text();
    }
  }
  return "<anonymous>";
}

/**
 * Parse a file and extract all symbols.
 */
export function extractSymbols(
  filePath: string,
  maxDepth: number = 2,
): { lang: string; symbols: SymbolInfo[] } | string {
  const lang = detectLanguage(filePath);
  if (!lang) {
    return `Unsupported file type: ${path.extname(filePath) || "(no extension)"}`;
  }

  const source = readFileText(filePath);
  if (source === null) {
    return `Could not read file: ${filePath}`;
  }

  const tree = parse(lang, source);
  const root = tree.root();
  const symbols = walkSymbols(root, lang as string, 1, maxDepth);

  return { lang: lang as string, symbols };
}

// ---------------------------------------------------------------------------
// Formatting
// ---------------------------------------------------------------------------

function formatSymbols(
  symbols: SymbolInfo[],
  indent: string = "  ",
): string {
  const lines: string[] = [];
  for (const sym of symbols) {
    const range = `${sym.startLine}-${sym.endLine}`;
    const kindLabel = sym.kind.replace(/_/g, " ");
    lines.push(`${indent}${range.padEnd(8)} ${kindLabel} ${sym.name}`);
    if (sym.children.length > 0) {
      lines.push(formatSymbols(sym.children, indent + "  "));
    }
  }
  return lines.join("\n");
}

function countSymbols(symbols: SymbolInfo[]): number {
  let count = symbols.length;
  for (const sym of symbols) {
    count += countSymbols(sym.children);
  }
  return count;
}

// ---------------------------------------------------------------------------
// Collect files helper (for potential multi-file use by later tools)
// ---------------------------------------------------------------------------

export function collectFiles(dirPath: string, extensions: string[]): string[] {
  const results: string[] = [];
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dirPath, entry.name);
      if (entry.isDirectory()) {
        // Skip hidden dirs and node_modules
        if (entry.name.startsWith(".") || entry.name === "node_modules") {
          continue;
        }
        results.push(...collectFiles(fullPath, extensions));
      } else if (extensions.some((ext) => entry.name.endsWith(ext))) {
        results.push(fullPath);
      }
    }
  } catch {
    // Ignore unreadable directories
  }
  return results;
}

// ---------------------------------------------------------------------------
// Language resolver for ast_grep
// ---------------------------------------------------------------------------

function resolveLang(lang: string): LangId {
  const map: Record<string, LangId> = {
    python: "python",
    typescript: Lang.TypeScript,
    tsx: Lang.Tsx,
    javascript: Lang.JavaScript,
    go: "go",
  };
  return map[lang] ?? lang;
}

// ---------------------------------------------------------------------------
// Directories to skip during file collection for ast_grep
// ---------------------------------------------------------------------------

const SKIP_DIRS = new Set([
  "__pycache__",
  ".venv",
  "venv",
  "dist",
  "build",
]);

// ---------------------------------------------------------------------------
// Extension entry point
// ---------------------------------------------------------------------------

export default function balooAstTools(pi: ExtensionAPI): void {
  pi.registerTool({
    name: "ast_outline",
    label: "AST Outline",
    description:
      "List all symbols (functions, classes, methods, interfaces, type aliases) in a file with their line ranges. " +
      "Useful for quickly understanding a file's structure without reading the full source.",
    parameters: Type.Object({
      path: Type.String({ description: "File path to outline" }),
      max_depth: Type.Optional(
        Type.Number({
          description: "Max nesting depth (default 2)",
          default: 2,
        }),
      ),
    }),
    async execute(
      _toolCallId: string,
      params: { path: string; max_depth?: number },
      _signal: AbortSignal,
      _onUpdate: unknown,
      _ctx: unknown,
    ) {
      const filePath = params.path;
      const maxDepth = params.max_depth ?? 2;

      const result = extractSymbols(filePath, maxDepth);

      if (typeof result === "string") {
        // Error message
        return {
          content: [{ type: "text" as const, text: result }],
          details: { symbolCount: 0 },
        };
      }

      const { lang, symbols } = result;

      if (symbols.length === 0) {
        const text = `${filePath} (${lang})\n  No symbols found.`;
        return {
          content: [{ type: "text" as const, text }],
          details: { symbolCount: 0 },
        };
      }

      const header = `${filePath} (${lang})`;
      const body = formatSymbols(symbols);
      const text = `${header}\n${body}`;
      const symbolCount = countSymbols(symbols);

      return {
        content: [{ type: "text" as const, text }],
        details: { symbolCount },
      };
    },
  });

  pi.registerTool({
    name: "ast_grep",
    label: "AST Grep",
    description:
      "Search for code patterns by structure using ast-grep. " +
      "Use $VAR to match any single expression/identifier, $$$ for multiple arguments or statements. " +
      "Examples: 'except $ERR: pass', 'subprocess.run($$$, shell=True)', 'if err != nil { return $$$, $ERR }'. " +
      "Supports Python, TypeScript, JavaScript, and Go.",
    parameters: Type.Object({
      pattern: Type.String({ description: "ast-grep pattern with metavariables ($VAR, $$$)" }),
      language: Type.String({ description: "Language: python, typescript, javascript, tsx, go" }),
      path: Type.Optional(Type.String({ description: "File or directory to search (defaults to cwd)" })),
    }),
    async execute(
      _toolCallId: string,
      params: { pattern: string; language: string; path?: string },
      _signal: AbortSignal,
      _onUpdate: unknown,
      ctx: { cwd?: string },
    ) {
      const { pattern, language } = params;
      const searchPath = params.path ?? ctx.cwd ?? ".";
      const langId = resolveLang(language);
      const extensions = LANG_EXTS[language];

      if (!extensions) {
        return {
          content: [{ type: "text" as const, text: `Unsupported language: ${language}` }],
        };
      }

      // Collect files, skipping extra directories beyond what collectFiles already skips
      function collectFilesFiltered(dirPath: string, exts: string[]): string[] {
        const results: string[] = [];
        try {
          const entries = fs.readdirSync(dirPath, { withFileTypes: true });
          for (const entry of entries) {
            const fullPath = path.join(dirPath, entry.name);
            if (entry.isDirectory()) {
              if (
                entry.name.startsWith(".") ||
                entry.name === "node_modules" ||
                SKIP_DIRS.has(entry.name)
              ) {
                continue;
              }
              results.push(...collectFilesFiltered(fullPath, exts));
            } else if (exts.some((ext) => entry.name.endsWith(ext))) {
              results.push(fullPath);
            }
          }
        } catch {
          // Ignore unreadable directories
        }
        return results;
      }

      // Determine if searchPath is a file or directory
      let files: string[];
      try {
        const stat = fs.statSync(searchPath);
        if (stat.isFile()) {
          files = [searchPath];
        } else {
          files = collectFilesFiltered(searchPath, extensions);
        }
      } catch {
        return {
          content: [{ type: "text" as const, text: `Path not found: ${searchPath}` }],
        };
      }

      // Cap at 500 files
      if (files.length > 500) {
        files = files.slice(0, 500);
      }

      const MAX_MATCHES = 30;
      const matchLines: string[] = [];
      let totalMatches = 0;
      let firstFileProcessed = false;

      outer: for (const filePath of files) {
        const source = readFileText(filePath);
        if (source === null) continue;

        let tree;
        try {
          tree = parse(langId, source);
        } catch {
          continue;
        }

        const sourceLines = source.split("\n");
        let matches;
        try {
          matches = tree.root().findAll(pattern);
        } catch (err) {
          if (!firstFileProcessed) {
            return {
              content: [
                {
                  type: "text" as const,
                  text: `Invalid pattern \`${pattern}\`: ${err}`,
                },
              ],
            };
          }
          continue;
        }
        firstFileProcessed = true;

        for (const node of matches) {
          if (totalMatches >= MAX_MATCHES) break outer;

          const range = node.range();
          const matchLine = range.start.line; // 0-indexed
          const displayLine = matchLine + 1;  // 1-indexed for display

          // Collect context: 1 line before, the match line, 1 line after
          const contextStart = Math.max(0, matchLine - 1);
          const contextEnd = Math.min(sourceLines.length - 1, matchLine + 1);
          const contextText = sourceLines
            .slice(contextStart, contextEnd + 1)
            .map((l, i) => `  ${l}`)
            .join("\n");

          matchLines.push(`${filePath}:${displayLine}\n${contextText}`);
          totalMatches++;
        }
      }

      if (totalMatches === 0) {
        return {
          content: [
            {
              type: "text" as const,
              text: `No matches for pattern \`${pattern}\` in ${searchPath}`,
            },
          ],
        };
      }

      const header = `Found ${totalMatches} match(es):\n`;
      const text = header + "\n" + matchLines.join("\n\n");

      return {
        content: [{ type: "text" as const, text }],
        details: { matchCount: totalMatches },
      };
    },
  });

  pi.registerTool({
    name: "ast_symbols",
    label: "AST Symbols",
    description:
      "Find where a symbol is defined and referenced across the codebase. " +
      "Definitions are located via AST patterns (precise); references are located via text search (line contains symbol name). " +
      "Useful for understanding how a function, class, or variable is used throughout the project.",
    parameters: Type.Object({
      name: Type.String({ description: "Symbol name to search for (e.g. 'validate_token')" }),
      language: Type.String({ description: "Language: python, typescript, javascript, tsx, go" }),
      path: Type.Optional(Type.String({ description: "Directory to search (defaults to cwd)" })),
    }),
    async execute(
      _toolCallId: string,
      params: { name: string; language: string; path?: string },
      _signal: AbortSignal,
      _onUpdate: unknown,
      ctx: { cwd?: string },
    ) {
      const { name: symbolName, language } = params;
      const searchPath = params.path ?? ctx.cwd ?? ".";
      const langId = resolveLang(language);
      const extensions = LANG_EXTS[language];

      if (!extensions) {
        return {
          content: [{ type: "text" as const, text: `Unsupported language: ${language}` }],
        };
      }

      // Collect files using the filtered variant (skips hidden dirs, node_modules, SKIP_DIRS)
      function collectFilesFiltered(dirPath: string, exts: string[]): string[] {
        const results: string[] = [];
        try {
          const entries = fs.readdirSync(dirPath, { withFileTypes: true });
          for (const entry of entries) {
            const fullPath = path.join(dirPath, entry.name);
            if (entry.isDirectory()) {
              if (
                entry.name.startsWith(".") ||
                entry.name === "node_modules" ||
                SKIP_DIRS.has(entry.name)
              ) {
                continue;
              }
              results.push(...collectFilesFiltered(fullPath, exts));
            } else if (exts.some((ext) => entry.name.endsWith(ext))) {
              results.push(fullPath);
            }
          }
        } catch {
          // Ignore unreadable directories
        }
        return results;
      }

      // Determine if searchPath is a file or directory
      let files: string[];
      try {
        const stat = fs.statSync(searchPath);
        if (stat.isFile()) {
          files = [searchPath];
        } else {
          files = collectFilesFiltered(searchPath, extensions);
        }
      } catch {
        return {
          content: [{ type: "text" as const, text: `Path not found: ${searchPath}` }],
        };
      }

      // Build language-specific definition patterns
      const defPatterns: string[] = [];
      if (language === "python") {
        defPatterns.push(
          `def ${symbolName}($$$)`,
          `class ${symbolName}($$$)`,
          `class ${symbolName}:`,
          `${symbolName} = $VALUE`,
        );
      } else if (
        language === "typescript" ||
        language === "javascript" ||
        language === "tsx"
      ) {
        defPatterns.push(
          `function ${symbolName}($$$)`,
          `class ${symbolName} $$$`,
          `const ${symbolName} = $$$`,
          `let ${symbolName} = $$$`,
          `interface ${symbolName} $$$`,
          `type ${symbolName} = $$$`,
          `export function ${symbolName}($$$)`,
          `export class ${symbolName} $$$`,
          `export const ${symbolName} = $$$`,
        );
      } else if (language === "go") {
        defPatterns.push(
          `func ${symbolName}($$$)`,
          `func ($RECV) ${symbolName}($$$)`,
          `type ${symbolName} $$$`,
          `var ${symbolName} $$$`,
        );
      }

      const MAX_DEFS = 20;
      const MAX_REFS = 20;

      interface SymbolMatch {
        file: string;
        line: number; // 1-indexed
        text: string; // trimmed line text
      }

      const definitions: SymbolMatch[] = [];
      // Track (file, line) pairs that are definitions, to exclude from references
      const defLineSet = new Set<string>();
      const references: SymbolMatch[] = [];

      for (const filePath of files) {
        const source = readFileText(filePath);
        if (source === null) continue;

        let tree;
        try {
          tree = parse(langId, source);
        } catch {
          continue;
        }

        const root = tree.root();
        const sourceLines = source.split("\n");

        // --- AST-based definition search ---
        for (const pattern of defPatterns) {
          if (definitions.length >= MAX_DEFS) break;
          let matches;
          try {
            matches = root.findAll(pattern);
          } catch {
            continue;
          }
          for (const node of matches) {
            if (definitions.length >= MAX_DEFS) break;
            const lineIdx = node.range().start.line; // 0-indexed
            const lineNum = lineIdx + 1; // 1-indexed
            const key = `${filePath}:${lineNum}`;
            if (defLineSet.has(key)) continue;
            defLineSet.add(key);
            definitions.push({
              file: filePath,
              line: lineNum,
              text: (sourceLines[lineIdx] ?? "").trimEnd(),
            });
          }
        }

        // --- Text-based reference search ---
        const escapedName = symbolName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
        const symbolRegex = new RegExp(`\\b${escapedName}\\b`);
        if (references.length < MAX_REFS) {
          for (let i = 0; i < sourceLines.length; i++) {
            if (references.length >= MAX_REFS) break;
            const lineNum = i + 1;
            const key = `${filePath}:${lineNum}`;
            if (defLineSet.has(key)) continue; // already a definition
            if (symbolRegex.test(sourceLines[i])) {
              references.push({
                file: filePath,
                line: lineNum,
                text: sourceLines[i].trim(),
              });
            }
          }
        }
      }

      // --- Format output ---
      const lines: string[] = [];
      lines.push(`Symbol: ${symbolName}`);
      lines.push("");

      if (definitions.length === 0) {
        lines.push("Defined in:");
        lines.push("  (none found)");
      } else {
        lines.push("Defined in:");
        for (const def of definitions) {
          lines.push(`  ${def.file}:${def.line}  ${def.text}`);
        }
      }

      lines.push("");

      if (references.length === 0) {
        lines.push("Referenced in:");
        lines.push("  (none found)");
      } else {
        lines.push("Referenced in:");
        for (const ref of references) {
          lines.push(`  ${ref.file}:${ref.line}   ${ref.text}`);
        }
      }

      const text = lines.join("\n");

      return {
        content: [{ type: "text" as const, text }],
        details: { definitions: definitions.length, references: references.length },
      };
    },
  });
}
