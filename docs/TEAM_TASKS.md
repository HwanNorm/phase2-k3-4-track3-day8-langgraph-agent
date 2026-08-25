# Phân công nhóm 2 người — Day 08 LangGraph Agent Lab

Repo được chia làm 2 mảng độc lập theo dependency order của lab:

- **P1 (Person 1) — State & Node Logic**: sở hữu `state.py` (phần logic) và toàn bộ 10 node trong `nodes.py`, bao gồm cả 2 node bắt buộc dùng LLM (`classify_node`, `answer_node`).
- **P2 (Person 2) — Routing, Graph & Infra**: sở hữu `routing.py`, `graph.py`, `persistence.py`, `metrics.py`, `report.py`.

Chỉ có **Checkpoint 0** và **Checkpoint cuối** làm chung. Phần còn lại mỗi người làm trên phần của mình, đồng bộ qua các checkpoint.

> Quy tắc chung: không hard-code theo `scenario_id` hoặc exact query text. Không sửa test để che lỗi implementation. Không commit `.env`, API key, hoặc `data/grading/`.

---

## Checkpoint 0 — State schema (LÀM CHUNG, ~20 phút)

**File:** `src/langgraph_agent_lab/state.py`

Cả hai cùng thống nhất trước khi tách việc, vì cả P1 và P2 đều phụ thuộc vào shape này:

- [ ] Thêm 4 field còn thiếu vào `AgentState`: `evaluation_result`, `pending_question`, `proposed_action`, `approval`
- [ ] Xác nhận: 4 field list (`messages`, `tool_results`, `errors`, `events`) dùng reducer `add` (append-only); mọi field scalar khác (kể cả 4 field mới) dùng overwrite
- [ ] Chạy `python -m pytest tests/test_state.py -q` → phải pass

**Done khi:** test_state.py xanh, cả hai người đều hiểu contract: *đọc state hiện tại → tính giá trị mới trong local variable → trả partial-update dict → không mutate input*.

---

## P1 — State & Node Logic

**Sở hữu:** `src/langgraph_agent_lab/nodes.py`, `src/langgraph_agent_lab/llm.py`, phần dữ liệu của `state.py`

### P1 · Checkpoint 1 — Nhánh không loop (~45 phút)

| Node | Đọc | Ghi | Lưu ý |
|---|---|---|---|
| `classify_node` | `query` | `route`, `risk_level`, event | **Bắt buộc LLM** — dùng `get_llm().with_structured_output(schema)`. Schema giới hạn `route` trong 5 giá trị. Prompt phải thể hiện priority `risky > tool > missing_info > error > simple`. Không đưa `scenario_id` vào prompt/logic. |
| `ask_clarification_node` | `query`; nếu rejected còn đọc `approval.comment`, `proposed_action` | overwrite `pending_question` + `final_answer`, event | Câu hỏi phải cụ thể, không chung chung |
| `risky_action_node` | `query`, `risk_level` | overwrite `proposed_action`, event | Chỉ đề xuất — **không** thực thi side effect ở đây |
| `approval_node` | `proposed_action` | overwrite `approval` = `{approved, reviewer, comment}`, event | Mock mặc định `approved=True` để CI/test không bị block. Không gọi tool trong node này |

**Done khi:** test thủ công từng node bằng state giả (dict tự tạo), xác nhận partial-update dict đúng shape; `classify_node` phân loại đúng 5 route với câu tự nghĩ (không phải 7 câu mẫu trong `scenarios.jsonl`).

### P1 · Checkpoint 2 — Tool loop (~45 phút)

| Node | Đọc | Ghi | Lưu ý |
|---|---|---|---|
| `tool_node` | `route`, `attempt`, `query` (risky: dựa trên action đã approved) | append 1 kết quả mới vào `tool_results`, event | Sinh lỗi khi `route == "error"` và `attempt < 2`. Không replace toàn bộ list |
| `evaluate_node` | phần tử **mới nhất** của `tool_results` | overwrite `evaluation_result` = `success`/`needs_retry`, event | Đọc nhầm phần tử đầu tiên là lỗi thường gặp |
| `retry_or_fallback_node` | `attempt`, `max_attempts` | overwrite `attempt = attempt + 1`, append error + event | **Chỉ node này** được tăng `attempt`. Không reset về 0 |
| `dead_letter_node` | `attempt`, `max_attempts`, `errors`, tool results cuối | overwrite `final_answer` (thông báo escalate), event | Chỉ có cạnh cố định tới `finalize`, không quay lại `tool`. Không đổi `route` |

**Done khi:** trace thủ công scenario `S07_dead_letter` (`max_attempts=1`): attempt 0→1 tại lần vào retry đầu tiên, `1 >= 1` → dead_letter ngay, không gọi tool lần 2.

### P1 · Checkpoint 3 — LLM answer + finalize (~30 phút)

| Node | Đọc | Ghi | Lưu ý |
|---|---|---|---|
| `answer_node` | `query`, `tool_results` liên quan, `approval`/`proposed_action` nếu có | overwrite `final_answer`, event | **Bắt buộc LLM** — grounded trên context thực tế, không hard-code câu trả lời, không tuyên bố action bị reject là đã thực hiện |
| `finalize_node` | `final_answer`/`pending_question` | append **duy nhất** finalize event | Không đổi `route` thành `done`/`dead_letter` — sẽ phá metric |

**Done khi:**
- `python -m pytest tests/test_state.py tests/test_metrics.py -q` pass
- Gọi `answer_node` độc lập với state giả, thấy câu trả lời do LLM sinh thực sự (không phải template tĩnh)

**Handoff cho P2:** báo P2 khi 11 node đã có ít nhất phần shape đúng (kể cả nếu logic LLM chưa hoàn thiện 100%), vì P2 · Checkpoint "Graph wiring" cần import được toàn bộ node.

---

## P2 — Routing, Graph & Infra

**Sở hữu:** `src/langgraph_agent_lab/routing.py`, `graph.py`, `persistence.py`, `metrics.py`, `report.py`

### P2 · Checkpoint 1 — Routing functions (~30 phút, làm song song với P1 · Checkpoint 1)

Có thể bắt đầu ngay sau Checkpoint 0 vì chỉ phụ thuộc state shape, không phụ thuộc node logic.

| Function | Điều kiện | Node tiếp theo |
|---|---|---|
| `route_after_classify` | `simple` | `answer` |
| | `tool` | `tool` |
| | `missing_info` | `clarify` |
| | `risky` | `risky_action` |
| | `error` | `retry` |
| | unknown/missing | `answer` (default) |
| `route_after_evaluate` | `evaluation_result == "needs_retry"` | `retry` |
| | mọi giá trị khác | `answer` |
| `route_after_retry` | `attempt < max_attempts` | `tool` |
| | `attempt >= max_attempts` | `dead_letter` |
| `route_after_approval` | `approval.approved is True` | `tool` |
| | false/không duyệt | `clarify` |

Routing function chỉ đọc state, trả tên node, **không gọi LLM, không mutate state, không side effect**.

**Done khi:** `python -m pytest tests/test_routing.py -q` pass hoàn toàn (dùng state giả, không cần chờ P1).

### P2 · Checkpoint 2 — Graph wiring (~30 phút, cần P1 handoff)

Đăng ký đúng 11 node (tên graph node = giá trị routing function trả về):

| Tên đăng ký | Python function |
|---|---|
| `intake` | `intake_node` (đã có sẵn) |
| `classify` | `classify_node` |
| `tool` | `tool_node` |
| `evaluate` | `evaluate_node` |
| `answer` | `answer_node` |
| `clarify` | `ask_clarification_node` |
| `risky_action` | `risky_action_node` |
| `approval` | `approval_node` |
| `retry` | `retry_or_fallback_node` |
| `dead_letter` | `dead_letter_node` |
| `finalize` | `finalize_node` |

Fixed edges: `START→intake`, `intake→classify`, `tool→evaluate`, `risky_action→approval`, `answer→finalize`, `clarify→finalize`, `dead_letter→finalize`, `finalize→END`.

Conditional edges sau `classify`, `evaluate`, `retry`, `approval` dùng 4 routing function của Checkpoint 1.

Compile với `checkpointer` được **truyền vào** `build_graph()` — không tự tạo checkpointer khác bên trong.

**Done khi:** `python -m pytest tests/test_graph_smoke.py -q` chạy được (cần API key + node LLM của P1 đã sẵn sàng); mọi route đều kết thúc ở `finalize → END`.

### P2 · Checkpoint 3 — Persistence (~30 phút)

- `persistence.py`: implement checkpointer (Memory bắt buộc cho core; SQLite là extension — dùng `SqliteSaver(conn=sqlite3.connect(...))`, **không** dùng `.from_conn_string()` — API cũ không còn hoạt động ở `langgraph-checkpoint-sqlite` 3.x)
- Xác nhận `thread_id` giữ ổn định trong 1 run, đổi thread cho scenario khác

**Done khi:** đọc lại được `get_state_history()` của một thread ngay sau khi `invoke` xong, trong cùng process.

### P2 · Checkpoint 4 — Metrics & Report (~45 phút, cần graph chạy được)

- `metrics.py`: rà `metric_from_state()` / `summarize_metrics()`. Cân nhắc đo `latency_ms` thật bằng `time.perf_counter()` quanh mỗi `graph.invoke` thay vì để mặc định 0
- `report.py`: implement `render_report()` sinh bảng Markdown từ `MetricsReport`

**Done khi:**
- `make run-scenarios` (hoặc `python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json` trên Windows) chạy hết 7 scenario
- `make grade-local` (hoặc `python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json`) pass
- `outputs/metrics.json` có ≥6 scenario, số liệu không toàn 0 mặc định vô nghĩa

---

## Checkpoint cuối — Tích hợp & Report (LÀM CHUNG, ~40 phút)

1. Chạy full gate cùng nhau:
   ```powershell
   python -m ruff check src tests
   python -m mypy src
   python -m pytest -q
   python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json
   python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json
   ```
2. Kiểm tra thủ công 2 trace quan trọng trong event trail:
   - **Risky approved:** `risky_action → approval → tool → evaluate → ... → finalize` (tool không được chạy trước approval)
   - **Error/dead-letter:** attempt tăng đúng từng bước; `S07_dead_letter` vào `dead_letter` ngay lần đầu vì `max_attempts=1`
3. Viết chung `reports/lab_report.md` (dùng `reports/lab_report_template.md` làm khung):
   - Kiến trúc 11 node + fixed/conditional edges + termination
   - Bảng metrics lấy từ `outputs/metrics.json` (không chép tay từ nguồn khác)
   - Ít nhất 2 failure mode cụ thể (vd: tool failure → bounded retry/dead-letter; risky action bị reject → clarification)
   - Persistence/recovery evidence (thread_id, state history, hoặc crash-resume — không chỉ nói "đã dùng MemorySaver")
   - Improvement plan: 1 ưu tiên productionize tiếp theo
4. `git status` sạch, giải thích được mọi file thay đổi; `git diff --check` không có whitespace error; không có secret trong Git

**Done khi:** submission checklist trong `README.md` đều tick, cả hai người đều giải thích được ít nhất 1 route và 1 failure mode khi demo.

---

## Bảng theo dõi tiến độ (điền khi làm)

| Checkpoint | Người phụ trách | Trạng thái | Ghi chú |
|---|---|---|---|
| 0 — State schema | Chung | ✅ | `state.py` đã thêm 4 field; `test_state.py` pass. `.venv` đã tạo và cài `pip install -e ".[dev]"` |
| P1.1 — Nhánh không loop | P1 | ✅ | classify/clarify/risky_action/approval done trên `CP1/Nam`, verify bằng câu tự nghĩ (không phải scenario mẫu), priority risky>tool xác nhận đúng |
| P2.1 — Routing functions | P2 | ✅ | 4 hàm routing đúng decision table, `test_routing.py` 13/13 pass |
| P1.2 — Tool loop | P1 | ✅ | tool/evaluate/retry/dead_letter done, trace S07 (max_attempts=1) xác nhận dead_letter ngay không loop vô hạn |
| P1.3 — LLM answer + finalize | P1 | ✅ | answer_node grounded LLM (Gemini gemini-3.6-flash), finalize_node xong |
| P2.2 — Graph wiring | P2 | ✅ | `build_graph()` đủ 11 node + 8 fixed edge + 4 conditional edge đúng. Live smoke test: 4/6 pass bằng Gemini trước khi hết quota free-tier (429) — 2 case fail là do quota, không phải bug wiring |
| P2.3 — Persistence | P2 | ✅ | `build_checkpointer("sqlite")` dùng `SqliteSaver(conn=...)` + WAL đúng pattern |
| P2.4 — Metrics & Report | P2 | ✅ | `render_report()` sinh đủ metrics summary, scenario table, architecture, failure analysis |
| **Merge P1 + P2 → main** | Chung | ✅ | PR #1 (`Son` → `main`) merged trên GitHub. `main` hiện có đủ 11 node + routing + graph + persistence + report. `test_state.py`/`test_metrics.py`/`test_routing.py`: 19/19 pass trên main sau merge |
| **BLOCKER — LLM quota/model** | Chung | ✅ | Added Groq fallback via `GROQ_API_KEY` using `openai/gpt-oss-20b`; structured classification and grounded answers verified. |
| Cuối — Tích hợp & Report | Chung | ✅ | `ruff`, `mypy`, and `pytest` pass; smoke is 6/6; 7 scenarios validate at 100%; report includes persistence evidence. |
