# Defining a Workflow Contract

A workflow contract is a YAML file that describes the minimum observable behavior a successful agent run must exhibit for one use case. The evaluator checks a trace against this contract using the plugin pipeline in the framework.

This guide is intentionally precise: it describes how contracts are interpreted by the implementation, not just what a contract should ideally look like.

## 1. What a contract is

A contract is not a procedural script and it is not a copy of one trace. It is a benchmark definition for a use case.

A good contract should:

- describe the goal of the workflow,
- state the observable requirements a successful run must satisfy,
- remain model-agnostic so different agents can solve the task in different ways,
- be strict enough to distinguish good runs from bad ones.

Unknown fields are rejected by the schema, so the contract must use only the supported structure.


## 2. Practical authoring workflow

1. Define the workflow goal.
2. List the required skills.
3. Identify the real resources involved.
4. Register those resources in `resources`.
5. Add `input_context` entries for anything that must be read.
6. Add `output` entries for anything that must be created or modified.
7. Add tool requirements and forbidden tools.
8. Validate the contract against a known good trace and a known bad trace.

## 3. Common mistakes

- Using invented resource names instead of real catalog names.
- Forgetting to add an explicit `path` for a non-standard resource.
- Treating `knowledge` as a requirement. It is only an exemption list.
- Making `input_context` too broad or too narrow.
- Making `output` too broad and accidentally allowing unrelated changes.
- Using `optional` tools as if they were required.
- Overfitting the contract to a single trace style.

## 4. Validation mindset

After writing a contract, test it against multiple traces:

1. one successful run,
2. one failing or incomplete run,
3. one run that changes unrelated files.

A good contract should clearly separate these cases.