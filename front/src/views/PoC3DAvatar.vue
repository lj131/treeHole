<template>
  <div class="poc-3d-avatar-page">
    <header class="poc-header">
      <h1>🎭 LIVE3D 立体人物 PoC</h1>
      <p class="poc-subtitle">Three.js VRM + Lip Sync 语音同步</p>
    </header>

    <div class="poc-controls">
      <div class="control-group">
        <label class="control-label">模型来源</label>
        <div class="model-selector">
          <button
            v-for="model in models"
            :key="model.id"
            :class="['model-btn', { active: currentModelId === model.id }]"
            @click="switchModel(model)"
          >
            <span class="model-icon">{{ model.icon }}</span>
            <span class="model-name">{{ model.name }}</span>
          </button>
        </div>
      </div>

      <div class="control-group">
        <label class="control-label">表情（Phase 4）</label>
        <div class="model-selector">
          <button
            v-for="expr in expressions"
            :key="expr.id"
            :class="['model-btn', { active: currentExpression === expr.id }]"
            @click="currentExpression = expr.id"
          >
            <span class="model-icon">{{ expr.icon }}</span>
            <span class="model-name">{{ expr.name }}</span>
          </button>
        </div>
      </div>

      <div class="control-group">
        <label class="control-label">Lip Sync 测试</label>
        <div class="audio-controls">
          <button
            class="action-btn play-btn"
            @click="playWavAudio"
            :disabled="isPlaying"
          >
            <span v-if="!isPlaying">▶ 播放 WAV（真实频谱）</span>
            <span v-else>⏸ 播放中...</span>
          </button>
          <button
            class="action-btn play-btn secondary"
            @click="playSpeechSim"
            :disabled="isPlaying"
          >
            🗣 TTS 模拟
          </button>
          <button
            class="action-btn stop-btn"
            @click="stopTestAudio"
            :disabled="!isPlaying"
          >
            ⏹ 停止
          </button>
        </div>
      </div>

      <div class="control-group">
        <label class="control-label">自定义模型 URL</label>
        <div class="custom-model-input">
          <input
            v-model="customModelUrl"
            type="text"
            placeholder="输入 VRM 文件 URL"
            class="url-input"
          />
          <button
            class="action-btn"
            @click="loadCustomModel"
            :disabled="!customModelUrl"
          >
            加载
          </button>
        </div>
      </div>
    </div>

    <div class="poc-stage">
      <div class="avatar-container">
        <VRMAvatar
          ref="avatarRef"
          :model-url="currentModelUrl"
          :width="440"
          :height="640"
          :transparent="false"
          background="#1a1a2e"
          :enable-controls="true"
          :lip-sync-audio="audioElement"
          :expression="currentExpression"
          :expression-weight="0.75"
          @model-loaded="onModelLoaded"
          @load-error="onModelError"
        />
        <p class="hint">拖拽旋转 · 滚轮缩放</p>
      </div>

      <div class="status-panel">
        <div class="status-item">
          <span class="status-label">当前模型:</span>
          <span class="status-value">{{ currentModelName }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">表情:</span>
          <span class="status-value">{{ currentExpression }}</span>
        </div>
        <div class="status-item">
          <span class="status-label">Lip Sync:</span>
          <span class="status-value" :class="{ active: isPlaying }">
            {{ isPlaying ? lipSyncMode : '待机' }}
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">加载状态:</span>
          <span class="status-value" :class="{ error: loadError }">
            {{ loadStatus }}
          </span>
        </div>
        <div class="status-item">
          <span class="status-label">音频时长:</span>
          <span class="status-value">{{ audioDuration }}s</span>
        </div>
      </div>
    </div>

    <!-- 隐藏的音频元素：真实频谱 lip-sync -->
    <audio ref="audioRef" preload="auto" @ended="onAudioEnded" />
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onBeforeUnmount } from 'vue';
import VRMAvatar, { type AvatarExpression } from '@/components/3d/VRMAvatar.vue';

const TEST_AUDIO_URL = '/models/test-audio.wav';

const models = [
  {
    id: 'rpm',
    name: 'Ready Player Me',
    icon: '👤',
    url: '/models/rpm_demo.vrm',
  },
  {
    id: 'vroid',
    name: 'VRoid Hub',
    icon: '🎨',
    url: '/models/vroid_demo.vrm',
  },
];

const expressions: { id: AvatarExpression; name: string; icon: string }[] = [
  { id: 'neutral', name: '中性', icon: '😐' },
  { id: 'happy', name: '开心', icon: '😊' },
  { id: 'angry', name: '生气', icon: '😠' },
  { id: 'sad', name: '难过', icon: '😢' },
  { id: 'surprised', name: '惊讶', icon: '😮' },
  { id: 'relaxed', name: '放松', icon: '😌' },
];

const currentModelId = ref('rpm');
const currentModelUrl = ref(models[0]!.url);
const currentModelName = ref(models[0]!.name);
const currentExpression = ref<AvatarExpression>('happy');
const customModelUrl = ref('');
const isPlaying = ref(false);
const lipSyncMode = ref('');
const audioDuration = ref(0);
const loadError = ref(false);
const loadStatus = ref('待加载');

const avatarRef = ref<InstanceType<typeof VRMAvatar>>();
const audioRef = ref<HTMLAudioElement>();

/** 仅在 WAV 播放时把 audio 交给 LipSyncEngine */
const useWavLipSync = ref(false);
const audioElement = computed(() =>
  useWavLipSync.value && isPlaying.value ? audioRef.value : null
);

let speechInterval: number | null = null;

const switchModel = (model: (typeof models)[0]) => {
  if (currentModelId.value === model.id) return;

  currentModelId.value = model.id;
  currentModelUrl.value = model.url;
  currentModelName.value = model.name;
  loadStatus.value = '加载中';
  loadError.value = false;
};

const loadCustomModel = () => {
  if (!customModelUrl.value) return;

  currentModelId.value = 'custom';
  currentModelUrl.value = customModelUrl.value;
  currentModelName.value = '自定义模型';
  loadStatus.value = '加载中';
  loadError.value = false;
};

const clearSpeechSim = () => {
  if (speechInterval !== null) {
    clearInterval(speechInterval);
    speechInterval = null;
  }
  window.speechSynthesis.cancel();
};

/**
 * 真实 WAV + Web Audio 频谱 → 嘴型
 */
const playWavAudio = async () => {
  if (!audioRef.value) return;

  clearSpeechSim();
  const audio = audioRef.value;
  audio.src = TEST_AUDIO_URL;
  audio.currentTime = 0;

  try {
    useWavLipSync.value = true;
    isPlaying.value = true;
    lipSyncMode.value = 'WAV 频谱同步';
    loadStatus.value = 'Lip Sync（真实音频）';
    await audio.play();
  } catch (err) {
    console.error('WAV 播放失败:', err);
    isPlaying.value = false;
    useWavLipSync.value = false;
    loadStatus.value = 'WAV 播放失败（检查 /models/test-audio.wav）';
  }
};

/**
 * 浏览器 TTS：无法接入 Web Audio，用随机嘴型模拟
 */
const playSpeechSim = () => {
  clearSpeechSim();
  useWavLipSync.value = false;

  const utterance = new SpeechSynthesisUtterance(
    '你好！这是一个测试语音，用于验证唇形同步功能。'
  );
  utterance.lang = 'zh-CN';
  utterance.rate = 1;
  utterance.pitch = 1;

  utterance.onstart = () => {
    isPlaying.value = true;
    lipSyncMode.value = 'TTS 模拟';
    loadStatus.value = 'Lip Sync（TTS 模拟）';
    speechInterval = window.setInterval(() => {
      avatarRef.value?.updateMorph?.(Math.random() * 0.8);
    }, 120);
  };

  utterance.onend = () => {
    clearSpeechSim();
    avatarRef.value?.updateMorph?.(0);
    isPlaying.value = false;
    loadStatus.value = '播放完成';
  };

  utterance.onerror = (e) => {
    clearSpeechSim();
    isPlaying.value = false;
    loadStatus.value = `语音合成失败: ${e.error}`;
  };

  try {
    window.speechSynthesis.speak(utterance);
  } catch {
    loadStatus.value = '浏览器不支持语音合成';
  }
};

const stopTestAudio = () => {
  clearSpeechSim();
  if (audioRef.value) {
    audioRef.value.pause();
    audioRef.value.currentTime = 0;
  }
  useWavLipSync.value = false;
  avatarRef.value?.updateMorph?.(0);
  isPlaying.value = false;
  loadStatus.value = '已停止';
};

const onAudioEnded = () => {
  useWavLipSync.value = false;
  isPlaying.value = false;
  loadStatus.value = '播放完成';
};

const onModelLoaded = () => {
  loadStatus.value = '加载成功';
  loadError.value = false;
};

const onModelError = (msg: string) => {
  loadStatus.value = `加载失败: ${msg}`;
  loadError.value = true;
};

onMounted(() => {
  if (!audioRef.value) return;
  audioRef.value.src = TEST_AUDIO_URL;
  audioRef.value.addEventListener('loadedmetadata', () => {
    audioDuration.value = Math.round(audioRef.value!.duration || 0);
  });
});

onBeforeUnmount(() => {
  stopTestAudio();
});
</script>

<style scoped>
.poc-3d-avatar-page {
  max-width: 1200px;
  margin: 0 auto;
  padding: 24px;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
}

.poc-header {
  text-align: center;
  margin-bottom: 32px;
}

.poc-header h1 {
  font-size: 28px;
  margin: 0 0 8px 0;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.poc-subtitle {
  color: #666;
  font-size: 14px;
  margin: 0;
}

.poc-controls {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 16px;
  margin-bottom: 24px;
}

.control-group {
  background: white;
  padding: 16px;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.control-label {
  display: block;
  font-size: 12px;
  font-weight: 600;
  color: #666;
  margin-bottom: 12px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.model-selector {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 8px;
}

.model-btn {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding: 16px 8px;
  border: 2px solid #e0e0e0;
  border-radius: 8px;
  background: white;
  cursor: pointer;
  transition: all 0.2s;
}

.model-btn:hover {
  border-color: #667eea;
  transform: translateY(-2px);
}

.model-btn.active {
  border-color: #667eea;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.model-icon {
  font-size: 24px;
  margin-bottom: 4px;
}

.model-name {
  font-size: 12px;
  font-weight: 500;
}

.audio-controls {
  display: flex;
  gap: 8px;
}

.action-btn {
  flex: 1;
  padding: 10px 16px;
  border: none;
  border-radius: 6px;
  font-size: 14px;
  font-weight: 500;
  cursor: pointer;
  transition: all 0.2s;
}

.action-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.play-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.play-btn.secondary {
  background: linear-gradient(135deg, #4facfe 0%, #00f2fe 100%);
}

.play-btn:hover:not(:disabled) {
  transform: scale(1.02);
}

.stop-btn {
  background: #f0f0f0;
  color: #333;
}

.stop-btn:hover:not(:disabled) {
  background: #e0e0e0;
}

.custom-model-input {
  display: flex;
  gap: 8px;
}

.url-input {
  flex: 1;
  padding: 10px 12px;
  border: 1px solid #e0e0e0;
  border-radius: 6px;
  font-size: 14px;
}

.url-input:focus {
  outline: none;
  border-color: #667eea;
}

.poc-stage {
  display: grid;
  grid-template-columns: 1fr 300px;
  gap: 24px;
}

.avatar-container {
  background: #12121f;
  border-radius: 16px;
  overflow: hidden;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.08);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  padding: 16px;
  min-height: 680px;
}

.hint {
  margin: 10px 0 0;
  font-size: 12px;
  color: #888;
}

.status-panel {
  background: white;
  padding: 20px;
  border-radius: 12px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.05);
}

.status-item {
  display: flex;
  justify-content: space-between;
  padding: 12px 0;
  border-bottom: 1px solid #f0f0f0;
}

.status-item:last-child {
  border-bottom: none;
}

.status-label {
  color: #666;
  font-size: 14px;
}

.status-value {
  font-weight: 500;
  font-size: 14px;
  color: #333;
}

.status-value.active {
  color: #4caf50;
}

.status-value.error {
  color: #f44336;
}

@media (max-width: 768px) {
  .poc-stage {
    grid-template-columns: 1fr;
  }

  .model-selector {
    grid-template-columns: 1fr;
  }
}
</style>