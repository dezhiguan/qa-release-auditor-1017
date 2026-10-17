import json
import re
from typing import Dict, Any, List

async def execute(data: dict, ctx) -> dict:
    # Extract required identifiers from input text
    text = data.get("text", "")
    if not isinstance(text, str):
        return {"decision": "BLOCKED", "reason": "input.text must be a string"}
    
    # Parse repo, runId, PR number, jobId from natural language
    repo_match = re.search(r"仓库\s+([\w\-]+)", text) or re.search(r"repo=([\w\-]+)", text)
    runId_match = re.search(r"CI\s+runId\s+(\d+)", text) or re.search(r"runId=(\d+)", text)
    pr_match = re.search(r"PR\s+#(\d+)", text) or re.search(r"PR\s+#(\d+)", text) or re.search(r"PR\s+number\s+(\d+)", text) or re.search(r"PR\s+#(\d+)", text)
    jobId_match = re.search(r"任务\s+DF-(\d+)", text) or re.search(r"jobId=DF-(\d+)", text) or re.search(r"DF-(\d+)", text)
    
    repo = repo_match.group(1) if repo_match else None
    runId = runId_match.group(1) if runId_match else None
    pr_number = pr_match.group(1) if pr_match else None
    jobId = f"DF-{jobId_match.group(1)}" if jobId_match else None
    
    # Validate all four identifiers present
    missing = []
    if not repo:
        missing.append("repo")
    if not runId:
        missing.append("runId")
    if not pr_number:
        missing.append("PR number")
    if not jobId:
        missing.append("jobId")
    
    if missing:
        return {
            "decision": "BLOCKED",
            "reason": f"Missing required identifiers: {', '.join(missing)}"
        }
    
    # Validate numeric formats
    if not runId.isdigit() or not pr_number.isdigit() or not jobId_match or not jobId_match.group(1).isdigit():
        return {
            "decision": "BLOCKED",
            "reason": "runId, PR number, and jobId suffix must be numeric"
        }
    
    # Check delegate list
    allowed_delegates = list(ctx.manifest.spec.delegates or [])
    if len(allowed_delegates) < 2:
        return {
            "decision": "BLOCKED",
            "reason": "Less than two authorized delegates available"
        }
    
    # Tool calls — must use exact kwarg names per契约
    try:
        job_result = await ctx.tools.call("devflow.job.read", jobId=jobId)
    except Exception:
        return {"decision": "BLOCKED", "reason": "devflow.job.read call failed"}
    
    try:
        ci_result = await ctx.tools.call("ci.log.fetch", repo=repo, runId=runId)
    except Exception:
        return {"decision": "BLOCKED", "reason": "ci.log.fetch call failed"}
    
    try:
        pr_diff_result = await ctx.tools.call("git.pr.diff", repo=repo, number=int(pr_number))
    except Exception:
        return {"decision": "BLOCKED", "reason": "git.pr.diff call failed"}
    
    # Validate tool returns per契约
    if not isinstance(job_result, list):
        return {"decision": "BLOCKED", "reason": "devflow.job.read returned non-list"}
    if len(job_result) == 0:
        return {"decision": "BLOCKED", "reason": "devflow.job.read returned empty list"}
    
    if not isinstance(ci_result, dict) or "log" not in ci_result:
        return {"decision": "BLOCKED", "reason": "ci.log.fetch missing 'log' field"}
    
    if not isinstance(pr_diff_result, dict) or "diff" not in pr_diff_result or "number" not in pr_diff_result:
        return {"decision": "BLOCKED", "reason": "git.pr.diff missing 'diff' or 'number' field"}
    
    # Delegate to two sub-agents
    sub_results = []
    for name in allowed_delegates[:2]:
        try:
            # Construct task-specific prompt for each delegate
            delegate_input = f"Review evidence for repo={repo}, runId={runId}, PR #{pr_number}, jobId={jobId}. Use only provided tools' outputs. Do NOT infer, approve, or merge. Output structured analysis only."
            delegate_res = await ctx.delegate(name, delegate_input)
            if not isinstance(delegate_res, dict) or "result" not in delegate_res:
                return {"decision": "BLOCKED", "reason": f"Delegate {name} returned malformed response"}
            if not delegate_res["result"]:
                return {"decision": "BLOCKED", "reason": f"Delegate {name} returned empty result"}
            sub_results.append({"agent": name, "result": delegate_res["result"]})
        except Exception as e:
            return {"decision": "BLOCKED", "reason": f"Delegate {name} invocation failed: {str(e)}"}
    
    # Compile final prompt
    prompt = await ctx.prompt("role")
    compiled_prompt = prompt.compile(
        input={
            "repo": repo,
            "runId": runId,
            "pr_number": pr_number,
            "jobId": jobId,
            "sub_agent_results": sub_results,
            "job_result": job_result,
            "ci_result": ci_result,
            "pr_diff_result": pr_diff_result
        }
    )
    
    # LLM synthesis
    try:
        llm_response = await ctx.llm.chat([
            {"role": "user", "content": compiled_prompt}
        ])
    except Exception:
        return {"decision": "BLOCKED", "reason": "LLM synthesis failed"}
    
    # Parse decision from LLM output (must be exactly PASS or BLOCKED)
    decision_match = re.search(r'"decision":\s*"(PASS|BLOCKED)"', llm_response)
    if not decision_match:
        return {"decision": "BLOCKED", "reason": "LLM response missing valid decision field"}
    
    decision = decision_match.group(1)
    
    # Final output structure
    return {
        "decision": decision,
        "evidence": {
            "job": job_result,
            "ci_log": {"log": ci_result["log"]},
            "pr_diff": {"diff": pr_diff_result["diff"]},
            "sub_agents": sub_results
        },
        "steps": [
            "parsed identifiers",
            "validated delegates",
            "called devflow.job.read, ci.log.fetch, git.pr.diff",
            "delegated to two sub-agents",
            "synthesized with LLM"
        ],
        "input": {
            "repo": repo,
            "runId": runId,
            "pr_number": pr_number,
            "jobId": jobId
        }
    }