# Component Onboarding — Flow Diagrams (Left-to-Right)

---

## 1. ODH Component Onboarding

```mermaid
flowchart LR
    classDef both    fill:#D4EDDA,stroke:#2D7D46,color:#154420
    classDef odhOnly fill:#DDEEFF,stroke:#1A4A8A,color:#0d2045
    classDef cond    fill:#F5F5F5,stroke:#AAAAAA,color:#555555,stroke-dasharray:5 3
    classDef done    fill:#1A4A8A,stroke:#0d2045,color:#FFFFFF
    classDef decide  fill:#FFFBE6,stroke:#B8860B,color:#5a4000

    S1["1 · Validate"]:::both
    S2["2 · Quay Repo"]:::both
    S3["3 · Konflux<br/>Release Data"]:::both
    S4["4 · Konflux<br/>Central"]:::both
    S5["5 · ODH<br/>Onboarder"]:::odhOnly
    OP{"Operator?"}:::decide
    S6["6 · ODH<br/>Operator"]:::cond
    S7["7 · Bundle<br/>Config"]:::both
    DONE(["Jira to Review"]):::done

    S1 --> S2 --> S3
    S2 --> S4
    S3 --> S5
    S4 --> S5
    S5 --> OP
    OP -->|Yes| S6 --> S7
    OP -->|No|  S7
    S7 --> DONE
```

| 🟢 Green | Both ODH & RHOAI | 🔵 Blue | ODH only | ⬜ Grey dashed | Conditional |

---

## 2. RHOAI Component Onboarding

```mermaid
flowchart LR
    classDef both    fill:#D4EDDA,stroke:#2D7D46,color:#154420
    classDef rhoai   fill:#FFE5E5,stroke:#CC0000,color:#660000
    classDef cond    fill:#F5F5F5,stroke:#AAAAAA,color:#555555,stroke-dasharray:5 3
    classDef done    fill:#1A4A8A,stroke:#0d2045,color:#FFFFFF
    classDef decide  fill:#FFFBE6,stroke:#B8860B,color:#5a4000

    S1["1 · Validate"]:::both
    S2["2 · Quay Repo"]:::both
    S3["3 · Konflux<br/>Release Data"]:::both
    S4a["4a · Push<br/>Pipelines"]:::both
    S4b["4b · Pull<br/>Pipelines"]:::rhoai
    S5["5 · Dockerfile<br/>Labels"]:::rhoai
    OP{"Operator?"}:::decide
    S6["6 · ODH<br/>Operator"]:::cond
    S7["7 · Bundle<br/>Config"]:::both
    S8["8 · Delivery<br/>Repo"]:::rhoai
    S9["9 · Product<br/>Listing"]:::rhoai
    S10["10 · Auto<br/>Merge"]:::rhoai
    S11["11 · Renovate"]:::rhoai
    DONE(["Jira to Review"]):::done

    S1 --> S2 --> S3 --> S4a
    S3 --> S4b
    S4a --> S5
    S4b --> S5
    S5 --> OP
    OP -->|Yes| S6 --> S7
    OP -->|No|  S7
    S7 --> S8 --> S9 --> S10 --> S11 --> DONE
```

| 🟢 Green | Both ODH & RHOAI | 🔴 Red | RHOAI only | ⬜ Grey dashed | Conditional |

---

## 3. GitLab CI — Component Onboarding Execution

```mermaid
flowchart LR
    classDef schedNode  fill:#DDEEFF,stroke:#1A4A8A,color:#0d2045
    classDef parentNode fill:#E8E8E8,stroke:#444444,color:#111111
    classDef artifact   fill:#F9F9F9,stroke:#999999,color:#444444,stroke-dasharray:4 2
    classDef childNode  fill:#D4EDDA,stroke:#2D7D46,color:#154420
    classDef grandNode  fill:#FFE5E5,stroke:#CC0000,color:#660000
    classDef jiraNode   fill:#FFF8E1,stroke:#B8860B,color:#5a4000
    classDef done       fill:#1A4A8A,stroke:#0d2045,color:#FFFFFF

    subgraph SCHED["Schedule"]
        SC["Every 2h<br/>API trigger"]:::schedNode
    end

    subgraph PARENT["Parent Pipeline"]
        P1["fetch-jira-issues"]:::parentNode
        P2[/"generated YAML<br/>artifact"/]:::artifact
        P3["trigger pipelines"]:::parentNode
        P1 --> P2 --> P3
    end

    subgraph CHILD["Child Pipeline — 1 job per issue"]
        C1["ISSUE-A"]:::childNode
        C2["ISSUE-B"]:::childNode
        C3["ISSUE-N ..."]:::childNode
    end

    subgraph GRAND["Grandchild x N — 2h timeout"]
        G1["Setup env"]:::grandNode
        G2["claude /skill<br/>JIRA_URL"]:::grandNode
        G1 --> G2
    end

    subgraph JIRA["Jira — State Tracking"]
        J1["Labels<br/>updated"]:::jiraNode
        J2["PRs/MRs<br/>linked"]:::jiraNode
        J3["Jira to Review"]:::done
        J1 --> J2 --> J3
    end

    SC --> P1
    P3 --> C1
    P3 --> C2
    P3 --> C3
    C1 --> G1
    C2 --> G1
    C3 --> G1
    G2 --> J1
```

| 🔵 Blue | Schedule | ⬜ Grey | Parent pipeline | 🟢 Green | Child jobs | 🔴 Red | Grandchild — Claude | 🟡 Amber | Jira state |
