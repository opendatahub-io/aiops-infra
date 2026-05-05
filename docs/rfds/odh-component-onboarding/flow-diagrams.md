# Component Onboarding — Flow Diagrams

---

## 1. ODH Component Onboarding

```mermaid
flowchart TD
    classDef both      fill:#D4EDDA,stroke:#2D7D46,color:#154420,font-weight:bold
    classDef odhOnly   fill:#DDEEFF,stroke:#1A4A8A,color:#0d2045,font-weight:bold
    classDef cond      fill:#F5F5F5,stroke:#AAAAAA,color:#555555,stroke-dasharray:5 3
    classDef jira      fill:#FFF8E1,stroke:#B8860B,color:#5a4000
    classDef done      fill:#1A4A8A,stroke:#0d2045,color:#FFFFFF,font-weight:bold

    JIRA([📋 Jira — YAML Attachment-Single Source of Truth]):::jira

    S1[Validate Jira YAML & Input]:::both
    S2[Create Quay Repository]:::both
    S3[Onboard to Konflux Release Data]:::both
    S4[Add Pipelines to Konflux Central]:::both
    S5[Run ODH Onboarder Workflow]:::odhOnly
    OP{Operator or-Controller?}
    S6[Integrate with ODH Operator]:::cond
    S7[Bundle Configuration Update]:::both
    DONE([✅ Summary Posted · Jira → Review]):::done

    JIRA --> S1 --> S2 --> S3 & S4
    S3 & S4 -->|"merged ➜ triggers"| S5
    S5 --> OP
    OP -->|Yes| S6 --> S7
    OP -->|No| S7
    S7 --> DONE
```

**Color legend**

| Color | Meaning |
|-------|---------|
| 🟢 Green | Both ODH & RHOAI (standard steps) |
| 🔵 Blue | ODH only |
| ⬜ Grey dashed | Conditional — operator/controller only |

---

## 2. RHOAI Component Onboarding

```mermaid
flowchart TD
    classDef both     fill:#D4EDDA,stroke:#2D7D46,color:#154420,font-weight:bold
    classDef rhoaiOnly fill:#FFE5E5,stroke:#CC0000,color:#660000,font-weight:bold
    classDef cond     fill:#F5F5F5,stroke:#AAAAAA,color:#555555,stroke-dasharray:5 3
    classDef jira     fill:#FFF8E1,stroke:#B8860B,color:#5a4000
    classDef done     fill:#1A4A8A,stroke:#0d2045,color:#FFFFFF,font-weight:bold

    JIRA([📋 Jira — YAML Attachment-Single Source of Truth]):::jira

    S1["**1 · Validate Jira YAML & Inputs**-Reads YAML from Jira attachment"]:::both
    S2["**2 · Create Quay Repository**-App Interface GitLab MR → quay.io/rh-aiml-eng"]:::both
    S3["**3 · Onboard to Konflux Release Data**-konflux-release-data GitLab MR"]:::both
    S4a["**4a · Add Push Pipelines**-rhoai-konflux-central GitHub PR — Tekton push"]:::both
    S4b["**4b · Add Pull Pipelines** *(RHOAI only)*-rhoai-konflux-central GitHub PR — Tekton pull"]:::rhoaiOnly
    S5["**5 · Add Dockerfile Labels** *(RHOAI only)*-Component repo GitHub PR"]:::rhoaiOnly
    OP{Operator or-Controller?}
    S6["**6 · Integrate with ODH Operator**-odh-operator GitHub PR — manifests"]:::cond
    S7["**7 · Bundle Configuration**-ODH-Build-Config GitHub PR"]:::both
    S8["**8 · Create RHOAI Delivery Repo** *(RHOAI only)*-pyxis-repo-configs GitLab MR → registry.redhat.io"]:::rhoaiOnly
    S9["**9 · Update Product Listing** *(RHOAI only)*-rhoai-devops-infra GitHub PR"]:::rhoaiOnly
    S10["**10 · Setup Auto-Merge** *(RHOAI only)*-konflux-release-data GitLab MR"]:::rhoaiOnly
    S11["**11 · Enable Renovate** *(RHOAI only)*-rhoai-renovate GitHub PR"]:::rhoaiOnly
    DONE(["✅ Summary Posted · Jira → Review"]):::done

    JIRA --> S1 --> S2 --> S3
    S3 --> S4a & S4b
    S4a & S4b --> S5 --> OP
    OP -->|Yes| S6 --> S7
    OP -->|No| S7
    S7 --> S8 --> S9 --> S10 --> S11 --> DONE
```

**Color legend**

| Color | Meaning |
|-------|---------|
| 🟢 Green | Both ODH & RHOAI (standard steps) |
| 🔴 Red | RHOAI only |
| ⬜ Grey dashed | Conditional — operator/controller only |

---

## 3. GitLab CI — Component Onboarding Execution Flow

```mermaid
flowchart TD
    classDef scheduleNode fill:#DDEEFF,stroke:#1A4A8A,color:#0d2045,font-weight:bold
    classDef parentNode   fill:#E8E8E8,stroke:#333333,color:#111111,font-weight:bold
    classDef childNode    fill:#D4EDDA,stroke:#2D7D46,color:#154420,font-weight:bold
    classDef grandNode    fill:#FFE5E5,stroke:#CC0000,color:#660000,font-weight:bold
    classDef jiraNode     fill:#FFF8E1,stroke:#B8860B,color:#5a4000
    classDef artifact     fill:#F0F0F0,stroke:#888888,color:#333333,stroke-dasharray:4 2

    subgraph SCHED["⏱  SCHEDULE — every 2 hours via GitLab API"]
        direction LR
        SC["GitLab Pipeline Schedule-`pipeline_source = api`"]:::scheduleNode
    end

    subgraph PARENT["PARENT PIPELINE — .gitlab-ci.yml"]
        direction LR
        P1["**fetch-jira-issues**-Queries Jira JQL-Finds open `component-onboarding` issues"]:::parentNode
        P2[["generated-child--pipelines.yml-*(artifact)*"]]:::artifact
        P3["**trigger-onboarding-pipelines**-Triggers the child pipeline artifact"]:::parentNode
        P1 -->|writes| P2 -->|included by| P3
    end

    subgraph CHILD["CHILD PIPELINE — generated-child-pipelines.yml  *(one trigger job per issue)*"]
        direction LR
        C1["trigger-RHOAIENG--**ISSUE-A**-JIRA_URL injected"]:::childNode
        C2["trigger-RHOAIENG--**ISSUE-B**-JIRA_URL injected"]:::childNode
        C3["trigger-RHOAIENG--**ISSUE-N** · · ·-runs in parallel"]:::childNode
    end

    subgraph GRANDCHILD["GRANDCHILD PIPELINE ×N — child-pipeline.yml  *(2-hour timeout)*"]
        direction LR
        G1["**setup-claude-ci**-Install CLI · write GCP creds-clone aiops-infra · register skills"]:::grandNode
        G2["**onboard-component**-`claude -p /&lt;skill&gt; &lt;JIRA_URL&gt;`-Idempotent · short-lived · exits fast"]:::grandNode
        G1 -->|before_script| G2
    end

    subgraph JIRA_STATE["JIRA — State & Progress Tracking"]
        direction LR
        J1["Labels set per step-`in-progress` / `needs-review`-`completed`"]:::jiraNode
        J2["PRs/MRs linked-in Jira comments-Full audit trail"]:::jiraNode
        J3["Jira → **Review**-when all PRs raised-Human review & merge cycle"]:::jiraNode
        J1 --> J2 --> J3
    end

    SC -->|triggers| P1
    P3 -->|spawns| C1 & C2 & C3
    C1 & C2 & C3 -->|each triggers| G1
    G2 -->|posts progress| J1
```

**Pipeline cascade**

| Level | File | Runs |
|-------|------|------|
| **Parent** | `.gitlab-ci.yml` | Once per schedule tick — discovers Jira issues |
| **Child** | `generated-child-pipelines.yml` (artifact) | Once — contains one trigger job per issue |
| **Grandchild** | `child-pipeline.yml` | N times in parallel — one per Jira issue |

**How it advances over time**

```
Tick 1  →  Raises all newly-unblocked PRs/MRs, exits
Tick 2  →  Detects what merged, raises next batch, exits
Tick N  →  All PRs merged → posts summary → Jira → Resolved
```
