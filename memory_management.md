# Auto AI Agent Memory System  
## Project Mapping and Reasoning Architecture


## Overview

This document defines how the Auto AI Agent maintains global project awareness, architectural consistency, and long-term reasoning capability.

The memory system is designed to prevent:

- Context overload  
- Architectural drift  
- Short-term decision making  
- Repeated design mistakes  
- Loss of global project understanding  

The system is divided into structured memory layers that separate stable knowledge from dynamic project state.


# Memory Layer Architecture

The system consists of four primary layers:

1. Project Constitution  
2. Semantic Project Index  
3. Decision Log  
4. On-Demand Deep Retrieval  

Each layer serves a specific purpose and must not be merged into a single flat context dump.


# 1. Project Constitution

Location:
/project_memory/constitution.json

## Purpose

Defines the permanent identity and constraints of the project.

This file is always loaded during planning and review phases.

## Contents

- Project goal  
- Target users  
- Tech stack  
- Architecture style  
- Deployment environment  
- Non-negotiable rules  
- Performance constraints  
- Security constraints  

## Example Structure

{
  "goal": "Local-first autonomous AI coding assistant",
  "tech_stack": ["Python 3.12", "GTK4"],
  "architecture_style": "Modular MVC",
  "deployment": "Linux desktop",
  "constraints": [
    "No required cloud services",
    "Must run offline"
  ]
}

## Rules

- Changes are rare and intentional.  
- Architectural shifts require a decision log entry.  
- All task planning must validate alignment with this file.  

This prevents long-term architectural drift.


# 2. Semantic Project Index

Location:
/project_memory/index.json

## Purpose

Provides a structured, summarized representation of the entire project without loading all source files.

This replaces raw file dumping into prompts.

## Each File Entry Contains

- Path  
- Purpose  
- Responsibilities  
- Public interfaces  
- Dependencies  
- Dependents  
- Architectural notes  
- Known issues  

## Example Entry

{
  "path": "ui/main_window.py",
  "purpose": "Main GTK application window",
  "responsibilities": [
    "Render chat interface",
    "Manage layout",
    "Dispatch user input to agent"
  ],
  "public_interfaces": [
    "MainWindow.start_chat()"
  ],
  "depends_on": [
    "agent.py",
    "task_manager.py"
  ],
  "used_by": [],
  "notes": "Needs async safety improvements"
}

## Maintenance Strategy

- Automatically updated when files change  
- Generated via AST parsing + AI summarization  
- Only modified entries are recalculated  

## Why This Exists

- Reduces token usage  
- Maintains structural awareness  
- Enables dependency analysis  
- Allows targeted retrieval  


# 3. Decision Log

Location:
/project_memory/decisions.json

## Purpose

Stores architectural reasoning history.

Prevents repeated mistakes and ensures consistency across long-term development.

## Each Decision Contains

- ID  
- Title  
- Context  
- Reasoning  
- Tradeoffs  
- Risks  
- Long-term impact  
- Date  

## Example

{
  "id": 12,
  "title": "Adopt task graph execution model",
  "context": "Linear task queue caused dependency issues",
  "reasoning": "Graph model allows parallelism and retry logic",
  "tradeoffs": [
    "Increased implementation complexity"
  ],
  "risks": [
    "Harder debugging"
  ],
  "impact": "Core execution engine changed"
}

## Rules

- Required for major architecture changes  
- Must be checked before new structural modifications  
- Cannot be silently overridden  

This provides historical continuity and design stability.


# 4. On-Demand Deep Retrieval

## Purpose

Prevents full-project context overload.

## Workflow

1. Use semantic index to locate relevant files  
2. Retrieve only necessary file contents  
3. Perform task-specific modifications  
4. Update index entries for modified files  

Never load the entire project unless performing a global audit.

This ensures scalability for large projects.

# Reasoning Workflow Integration

For every task:

1. Load Constitution  
2. Load Decision Log  
3. Load Semantic Index  
4. Validate alignment  
5. Identify affected files  
6. Retrieve deep context only for those files  
7. Execute  
8. Update index  
9. Log new decisions if necessary  

This ensures:

- Global alignment  
- Local precision  
- Controlled architectural evolution  


# Milestone-Level Architectural Review

At milestone completion:

1. Load entire semantic index  
2. Analyze:
   - Dependency growth  
   - Coupling increase  
   - Duplicate responsibilities  
   - Expanding complexity  
3. Compare against constitution  
4. Generate refactor tasks if needed  

This prevents gradual degradation of system quality.


# Design Principles

The memory system enforces:

- Long-term architectural integrity over short-term speed  
- Explicit reasoning over implicit assumptions  
- Structured summaries over raw context dumping  
- Historical awareness over stateless execution  
- Controlled evolution over chaotic growth  


# Expected Outcomes

When properly implemented, this system enables the agent to:

- Maintain global project awareness  
- Detect architectural drift  
- Avoid redundant abstractions  
- Generate proactive refactor tasks  
- Scale to large multi-file projects  
- Operate closer to a senior software engineer  


# Implementation Summary

## Minimum Required Components

- constitution.json  
- index.json  
- decisions.json  
- Structured task orchestration engine  
- Automatic index updates after file modification  

## Optional Enhancements

- Dependency graph visualization  
- Coupling metrics  
- File complexity tracking  
- Architecture health scoring  
- Automated diff summaries before review phase  

