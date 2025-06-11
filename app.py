import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# ————————— 1. Google Sheets 인증 설정 —————————
scope = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]
creds = ServiceAccountCredentials.from_json_keyfile_dict(
    st.secrets["gcp_service_account"], scope
)
client      = gspread.authorize(creds)
spreadsheet = client.open_by_key(st.secrets["gcp_service_account"]["sheet_id"])

# ————————— 2. 동/층(시트) 선택 —————————
st.sidebar.header("동/층 선택")
worksheets = spreadsheet.worksheets()
floors     = [ws.title for ws in worksheets]
selection  = st.sidebar.selectbox("동/층", floors, index=0, key="floor_select")
building, floor_id = selection[0], selection[1:]
worksheet  = spreadsheet.worksheet(selection)

# ————————— 3. 데이터 로드 및 전처리 —————————
records = worksheet.get_all_records()
df      = pd.DataFrame(records)

# 3-1) 컬럼명 문자열화 → 앞뒤 공백·BOM 제거
df.columns = [str(c).strip().replace("\ufeff", "") for c in df.columns]

# 3-2) 한글 헤더를 영어 키명으로 자동 매핑
k2e = {
    "호실":      "room",
    "이름":      "name",
    "상태":      "status",
    "이전호실":  "prev_room",
    "이전상태":  "prev_status",
    "이동호실":  "new_room",
}
to_rename = {k: k2e[k] for k in df.columns if k in k2e}
df.rename(columns=to_rename, inplace=True)

# 3-3) 필수 컬럼 보장 및 결측치는 빈 문자열
for col in ["room", "name", "status", "prev_room", "prev_status", "new_room"]:
    if col not in df.columns:
        df[col] = ""
    else:
        df[col] = df[col].fillna("")

# 3-4) 'room' 칼럼 존재 확인
if "room" not in df.columns:
    st.error("'room' 컬럼이 없습니다. 시트 헤더를 확인하세요.")
    st.stop()

# 3-5) 호실 값 문자열 정리 및 빈 호실 제거
df["room"] = df["room"].astype(str).str.strip()
df = df[df["room"] != ""].copy()


# ————————— 4. 메인 화면: 배치표 —————————
st.title(f"기숙사 {building}동 {floor_id}층 현황판")
disp = df.set_index("room")[["name", "status"]]
disp = disp[~disp.index.duplicated(keep="first")]

styled = (
    disp.style
    .set_table_styles([
        {"selector": ".col0", "props": [("min-width", "100px")]},
        {"selector": ".col1", "props": [("min-width", "250px")]},
        {"selector": ".col2", "props": [("min-width", "120px")]},
    ])
    .set_properties(subset=["name", "status"], **{"text-align": "center"})
)
st.dataframe(styled, use_container_width=True)


# ————————— 5. 사이드바: 학생 정보 수정 —————————
st.sidebar.header("학생 정보 수정")
rooms = df["room"].tolist()
if not rooms:
    st.error("등록된 호실이 없습니다.")
    st.stop()

room = st.sidebar.selectbox("호실 선택", rooms, key="room_select")

# 선택한 호실이 실제로 있는지 매칭
matched = df.index[df["room"] == room].tolist()
if not matched:
    st.error(f"선택된 호실 '{room}' 정보가 없습니다.")
    st.stop()
idx = matched[0]

old_status = df.at[idx, "status"]
default_state = "초기화" if old_status else "외박"
states = ["퇴소", "외박", "이동", "신규", "초기화"]

new_name   = st.sidebar.text_input("학생 이름+번호", df.at[idx, "name"], key="name_input")
new_status = st.sidebar.selectbox("상태 변경", states, index=states.index(default_state), key="status_select")

new_room = ""
if new_status == "이동":
    avail = [r for r in rooms if r != room]
    new_room = st.sidebar.selectbox("이동할 호실", avail, key="move_select")


# ————————— 6. 저장 및 Google Sheets 업데이트 —————————
if st.sidebar.button("저장", key="save_btn"):
    # 이전 기록 보존
    df.at[idx, "prev_status"] = old_status
    df.at[idx, "prev_room"]   = room

    if new_status == "초기화":
        df.loc[idx, ["status", "new_room", "prev_status", "prev_room"]] = ["", "", "", ""]
    elif new_status in ["신규", "외박"]:
        df.at[idx, "name"]     = new_name
        df.at[idx, "status"]   = new_status
        df.at[idx, "new_room"] = ""
    elif new_status == "퇴소":
        df.at[idx, "name"]     = ""
        df.at[idx, "status"]   = "퇴소"
        df.at[idx, "new_room"] = ""
    else:  # 이동
        df.loc[idx, ["name", "status"]] = ["", ""]
        new_idx = df.index[df["room"] == new_room][0]
        df.loc[new_idx, ["name", "status", "prev_room", "prev_status", "new_room"]] = [
            new_name, "이동", room, old_status, new_room
        ]

    # Google Sheets에 반영
    worksheet.clear()
    worksheet.update([df.columns.tolist()] + df.values.tolist())

    # 화면 새로고침
    try:
        st.rerun()
    except AttributeError:
        try:
            st.experimental_rerun()
        except AttributeError:
            pass


# ————————— 7. 요약 정보 —————————
out_df   = df[df["status"] == "퇴소"]
away_df  = df[df["status"] == "외박"]
new_df   = df[df["status"] == "신규"]
mv_df    = df[df["status"] == "이동"]

in_moves   = mv_df[(mv_df["new_room"].str[:2] == selection) & (mv_df["prev_room"].str[:2] != selection)]
out_moves  = mv_df[(mv_df["prev_room"].str[:2] == selection) & (mv_df["new_room"].str[:2] != selection)]
same_moves = mv_df[(mv_df["new_room"].str[:2] == selection) & (mv_df["prev_room"].str[:2] == selection)]

plus  = len(in_moves) + len(same_moves)
minus = len(out_moves) + len(same_moves)

present = df[
    (df["name"].str.strip() != "")
    & (~df["status"].isin(["퇴소", "외박"]))
]

def fmt(df_slice):
    return ", ".join(df_slice.apply(lambda x: f"{x['room']} {x['name']}", axis=1))

def fmt_move(df_slice):
    return ", ".join(df_slice.apply(lambda x: f"{x['prev_room']} {x['name']} → {x['new_room']}", axis=1))

st.write(f"[{building}동 {floor_id}층]")
st.write(f"퇴소:   {len(out_df)} ({fmt(out_df) if not out_df.empty else '-'})")
st.write(f"외박:   {len(away_df)} ({fmt(away_df) if not away_df.empty else '-'})")
st.write(f"신규:   {len(new_df)} ({fmt(new_df) if not new_df.empty else '-'})")
st.write(f"이동:   +{plus}/-{minus} ({fmt_move(mv_df) if not mv_df.empty else '-'})")
st.write(f"현재원: {len(present)}")

