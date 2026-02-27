#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { cpSync, existsSync, mkdirSync, mkdtempSync, readdirSync, rmSync } from "node:fs";
import { homedir, tmpdir } from "node:os";
import { join, resolve } from "node:path";

const ALL_SKILLS = [
  "sift-stylus-porting-auditor",
  "sift-stylus-research",
  "sift-stylus-code-helper",
];

function usage() {
  console.log(`Usage:
  sift-stylus --repo <owner/repo> [options]

Options:
  --repo <owner/repo>          GitHub repository containing skills (required)
  --ref <git-ref>              Git ref to fetch (default: main)
  --skills <csv>               Skill names to install (default: all)
  --skills-root <path>         Skills root path in repo (default: skills)
  --target <path>              Install root (default: ~/.codex/skills)
  --force                      Overwrite existing installations
  --help                       Show this help

Examples:
  npx sift-stylus \\
    --repo getFairAI/angel-stylus-coding-assistant

  npx sift-stylus \\
    --repo getFairAI/angel-stylus-coding-assistant \\
    --skills sift-stylus-research
`);
}

function parseArgs(argv) {
  const parsed = {
    repo: "",
    ref: "main",
    skills: [...ALL_SKILLS],
    skillsRoot: "skills",
    target: "~/.codex/skills",
    force: false,
    help: false,
  };

  for (let i = 0; i < argv.length; i += 1) {
    const arg = argv[i];
    if (arg === "--help") {
      parsed.help = true;
      continue;
    }
    if (arg === "--force") {
      parsed.force = true;
      continue;
    }
    if (["--repo", "--ref", "--skills", "--skills-root", "--target"].includes(arg)) {
      const value = argv[i + 1];
      if (!value || value.startsWith("--")) {
        throw new Error(`Missing value for ${arg}`);
      }
      i += 1;
      if (arg === "--repo") parsed.repo = value;
      if (arg === "--ref") parsed.ref = value;
      if (arg === "--skills") {
        parsed.skills = value
          .split(",")
          .map((item) => item.trim())
          .filter(Boolean);
      }
      if (arg === "--skills-root") parsed.skillsRoot = value;
      if (arg === "--target") parsed.target = value;
      continue;
    }
    throw new Error(`Unknown argument: ${arg}`);
  }

  return parsed;
}

function expandHome(pathLike) {
  if (pathLike === "~") return homedir();
  if (pathLike.startsWith("~/")) return join(homedir(), pathLike.slice(2));
  return pathLike;
}

function run(command, args) {
  const result = spawnSync(command, args, { stdio: "inherit" });
  if (result.status !== 0) {
    throw new Error(`Command failed: ${command} ${args.join(" ")}`);
  }
}

function validateRepoSlug(repo) {
  return /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repo);
}

function main() {
  const args = parseArgs(process.argv.slice(2));
  if (args.help) {
    usage();
    return;
  }

  if (!args.repo) {
    usage();
    throw new Error("--repo is required");
  }

  if (!validateRepoSlug(args.repo)) {
    throw new Error("--repo must be in owner/repo format");
  }

  if (!args.skills.length) {
    throw new Error("No skills selected for installation");
  }

  const unknown = args.skills.filter((skill) => !ALL_SKILLS.includes(skill));
  if (unknown.length) {
    throw new Error(`Unsupported skill(s): ${unknown.join(", ")}`);
  }

  const tempDir = mkdtempSync(join(tmpdir(), "sift-stylus-skills-"));
  const archive = join(tempDir, "repo.tar.gz");
  const targetRoot = resolve(expandHome(args.target));

  try {
    const tarballUrl = `https://codeload.github.com/${args.repo}/tar.gz/${args.ref}`;

    run("curl", ["-fsSL", tarballUrl, "-o", archive]);
    run("tar", ["-xzf", archive, "-C", tempDir]);

    const extractedRoot = readdirSync(tempDir)
      .filter((name) => name !== "repo.tar.gz")
      .map((name) => join(tempDir, name))
      .find((candidate) => existsSync(candidate));

    if (!extractedRoot) {
      throw new Error("Could not find extracted repository contents");
    }

    mkdirSync(targetRoot, { recursive: true });

    for (const skill of args.skills) {
      const sourceDir = resolve(extractedRoot, args.skillsRoot, skill);
      const targetDir = join(targetRoot, skill);

      if (!existsSync(sourceDir)) {
        throw new Error(`Skill path not found in repo: ${args.skillsRoot}/${skill}`);
      }

      if (existsSync(targetDir)) {
        if (!args.force) {
          throw new Error(`Target already exists: ${targetDir}. Use --force to overwrite.`);
        }
        rmSync(targetDir, { recursive: true, force: true });
      }

      cpSync(sourceDir, targetDir, { recursive: true });
      console.log(`Installed ${skill} -> ${targetDir}`);
    }

    console.log("All selected skills installed successfully.");
  } finally {
    rmSync(tempDir, { recursive: true, force: true });
  }
}

try {
  main();
} catch (error) {
  console.error(error instanceof Error ? error.message : String(error));
  process.exit(1);
}
