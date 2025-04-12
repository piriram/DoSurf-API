// functions/index.js
const functions = require("firebase-functions");
const admin = require("firebase-admin");
const { execSync } = require("child_process");

admin.initializeApp();

/**
 * 스케줄 기반 예보 수집 함수
 * 
 * 실행 시간: 02:15, 05:15, 08:15, 11:15, 14:15, 17:15, 20:15, 23:15 (KST)
 * - 기상청 단기예보 발표: 02:00, 05:00, 08:00, 11:00, 14:00, 17:00, 20:00, 23:00
 * - API 제공 시간: 발표 후 10분 (02:10, 05:10, ...)
 * - 실행 시간: API 제공 + 5분 (안정적 데이터 확보)
 */
exports.scheduledForecastCollect = functions
  .region("asia-northeast3")
  .runWith({
    timeoutSeconds: 540,  // 9분 (최대 실행 시간)
    memory: "1GB"
  })
  .pubsub
  .schedule("15 2,5,8,11,14,17,20,23 * * *")  // 매일 8회, 정시 + 15분
  .timeZone("Asia/Seoul")
  .onRun(async (context) => {
    console.log("🌊 예보 수집 시작:", new Date().toISOString());
    
    try {
      const result = execSync("python3 main.py", {
        cwd: __dirname,
        encoding: "utf-8",
        stdio: "pipe",
        maxBuffer: 10 * 1024 * 1024  // 10MB buffer
      });
      
      console.log("✅ 예보 수집 완료:", result);
      return null;
    } catch (error) {
      console.error("❌ 예보 수집 실패:", error.message);
      if (error.stdout) console.log("stdout:", error.stdout);
      if (error.stderr) console.error("stderr:", error.stderr);
      throw new functions.https.HttpsError("internal", "예보 수집 중 오류 발생");
    }
  });

/**
 * HTTP 트리거 기반 수동 수집 함수
 * 
 * 사용: https://asia-northeast3-[PROJECT-ID].cloudfunctions.net/collectForecast
 * 테스트 및 수동 실행용
 */
exports.collectForecast = functions
  .region("asia-northeast3")
  .runWith({
    timeoutSeconds: 540,
    memory: "1GB"
  })
  .https
  .onRequest(async (req, res) => {
    console.log("🌊 수동 예보 수집 시작:", new Date().toISOString());
    
    try {
      const result = execSync("python3 main.py", {
        cwd: __dirname,
        encoding: "utf-8",
        stdio: "pipe",
        maxBuffer: 10 * 1024 * 1024
      });
      
      console.log("✅ 수동 예보 수집 완료:", result);
      res.status(200).json({
        success: true,
        message: "예보 수집 완료",
        output: result
      });
    } catch (error) {
      console.error("❌ 수동 예보 수집 실패:", error.message);
      res.status(500).json({
        success: false,
        message: "예보 수집 실패",
        error: error.message,
        stdout: error.stdout,
        stderr: error.stderr
      });
    }
  });