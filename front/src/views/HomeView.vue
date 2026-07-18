<template>
  <div class="home">
    <!-- Hero Section -->
    <section class="hero">
      <div class="hero-content">
        <h1 class="hero-title">
          Your Chat
          <span class="gradient-text">AI Test Project</span>
        </h1>
        <p class="hero-subtitle">
          探索人工智能的无限可能，体验智能对话的魅力
        </p>
        <div class="hero-actions">
          <router-link to="/chat" class="primary-btn">
            开始对话
          </router-link>
          <router-link to="/characters" class="secondary-btn">
            角色管理
          </router-link>
          <router-link to="/memory" class="secondary-btn">
            记忆中心
          </router-link>
          <router-link to="/about" class="secondary-btn">
            了解更多
          </router-link>
          <router-link to="/poc-3d" class="secondary-btn" style="background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);">
            🎭 LIVE3D 测试
          </router-link>
        </div>
      </div>
      <div class="hero-visual">
        <div class="floating-card">
          <div class="card-icon">💬</div>
          <h3>智能对话</h3>
          <p>与AI角色进行自然流畅的对话</p>
        </div>
        <div class="floating-card" style="animation-delay: 0.2s;">
          <div class="card-icon">🧠</div>
          <h3>记忆系统</h3>
          <p>AI会记住你的喜好和对话历史</p>
        </div>
        <div class="floating-card" style="animation-delay: 0.4s;">
          <div class="card-icon">🎯</div>
          <h3>个性互动</h3>
          <p>根据你的反馈调整互动方式</p>
        </div>
      </div>
    </section>

    <!-- Features Section -->
    <section class="features">
      <h2 class="section-title">核心特性</h2>
      <div class="features-grid">
        <div class="feature-card">
          <div class="feature-icon">🤖</div>
          <h3>智能对话</h3>
          <p>基于先进的大语言模型技术，提供自然、流畅的对话体验</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">🎭</div>
          <h3>角色扮演</h3>
          <p>多样化的角色选择，每个角色都有独特的性格和背景故事</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">💝</div>
          <h3>情感系统</h3>
          <p>动态的好感度系统，随着对话深入关系会发生变化</p>
        </div>
        <div class="feature-card">
          <div class="feature-icon">📚</div>
          <h3>记忆功能</h3>
          <p>AI会记住重要信息，让对话更有连贯性和个性化</p>
        </div>
      </div>
    </section>

    <!-- Stats Section -->
    <section class="stats">
      <div class="stats-container">
        <div class="stat-item">
          <div class="stat-number">100%</div>
          <div class="stat-label">隐私保护</div>
        </div>
        <div class="stat-item">
          <div class="stat-number">24/7</div>
          <div class="stat-label">随时对话</div>
        </div>
        <div class="stat-item">
          <div class="stat-number">∞</div>
          <div class="stat-label">无限可能</div>
        </div>
      </div>
    </section>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

// 页面滚动动画
onMounted(() => {
  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('fade-in')
      }
    })
  }, { threshold: 0.1 })

  document.querySelectorAll('.feature-card').forEach(card => {
    observer.observe(card)
  })
})
</script>

<style scoped>
.home {
  min-height: 100vh;
  background: linear-gradient(135deg, #0f0f23 0%, #1a1a2e 100%);
  color: white;
  overflow-x: hidden;
}

/* Hero Section */
.hero {
  padding: 80px 20px;
  text-align: center;
  position: relative;
  overflow: hidden;
}

.hero::before {
  content: '';
  position: absolute;
  top: -50%;
  left: -50%;
  width: 200%;
  height: 200%;
  background: radial-gradient(circle, rgba(99, 102, 241, 0.1) 0%, transparent 70%);
  animation: rotate 30s linear infinite;
}

@keyframes rotate {
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

.hero-content {
  position: relative;
  z-index: 1;
  max-width: 800px;
  margin: 0 auto;
}

.hero-title {
  font-size: 3.5rem;
  font-weight: 800;
  margin-bottom: 20px;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.gradient-text {
  font-size: 2rem;
  color: #a78bfa;
}

.hero-subtitle {
  font-size: 1.25rem;
  color: #a1a1aa;
  margin-bottom: 40px;
  line-height: 1.6;
}

.hero-actions {
  display: flex;
  gap: 20px;
  justify-content: center;
  flex-wrap: wrap;
}

.primary-btn, .secondary-btn {
  padding: 16px 32px;
  border-radius: 12px;
  text-decoration: none;
  font-weight: 600;
  transition: all 0.3s ease;
  display: inline-block;
}

.primary-btn {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
}

.primary-btn:hover {
  transform: translateY(-2px);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
}

.secondary-btn {
  background: rgba(255, 255, 255, 0.1);
  color: white;
  border: 1px solid rgba(255, 255, 255, 0.2);
}

.secondary-btn:hover {
  background: rgba(255, 255, 255, 0.2);
  transform: translateY(-2px);
}

.hero-visual {
  margin-top: 60px;
  display: flex;
  justify-content: center;
  gap: 30px;
  flex-wrap: wrap;
}

.floating-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 30px;
  width: 250px;
  text-align: center;
  animation: float 6s ease-in-out infinite;
  transition: transform 0.3s ease;
}

.floating-card:hover {
  transform: translateY(-10px);
}

@keyframes float {
  0%, 100% { transform: translateY(0px); }
  50% { transform: translateY(-20px); }
}

.card-icon {
  font-size: 2.5rem;
  margin-bottom: 15px;
}

.floating-card h3 {
  font-size: 1.25rem;
  margin-bottom: 10px;
  color: #e2e8f0;
}

.floating-card p {
  font-size: 0.9rem;
  color: #94a3b8;
  line-height: 1.5;
}

/* Features Section */
.features {
  padding: 100px 20px;
  max-width: 1200px;
  margin: 0 auto;
}

.section-title {
  text-align: center;
  font-size: 2.5rem;
  font-weight: 700;
  margin-bottom: 60px;
  background: linear-gradient(135deg, #f59e0b 0%, #ef4444 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
}

.features-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
  gap: 30px;
}

.feature-card {
  background: rgba(255, 255, 255, 0.05);
  backdrop-filter: blur(10px);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 20px;
  padding: 40px 30px;
  text-align: center;
  transition: all 0.3s ease;
  opacity: 0;
  transform: translateY(30px);
}

.feature-card.fade-in {
  opacity: 1;
  transform: translateY(0);
}

.feature-card:hover {
  background: rgba(255, 255, 255, 0.08);
  transform: translateY(-5px);
  box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
}

.feature-icon {
  font-size: 3rem;
  margin-bottom: 20px;
}

.feature-card h3 {
  font-size: 1.5rem;
  margin-bottom: 15px;
  color: #f1f5f9;
}

.feature-card p {
  color: #94a3b8;
  line-height: 1.6;
  font-size: 1rem;
}

/* Stats Section */
.stats {
  background: rgba(255, 255, 255, 0.03);
  padding: 80px 20px;
  margin-top: 100px;
}

.stats-container {
  max-width: 800px;
  margin: 0 auto;
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 40px;
  text-align: center;
}

.stat-item {
  padding: 20px;
}

.stat-number {
  font-size: 3rem;
  font-weight: 800;
  background: linear-gradient(135deg, #10b981 0%, #3b82f6 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  margin-bottom: 10px;
}

.stat-label {
  font-size: 1.1rem;
  color: #a1a1aa;
  text-transform: uppercase;
  letter-spacing: 1px;
}

/* Responsive */
@media (max-width: 768px) {
  .hero-title {
    font-size: 2.5rem;
  }

  .gradient-text {
    font-size: 1.5rem;
  }

  .hero-subtitle {
    font-size: 1.1rem;
  }

  .floating-card {
    width: 200px;
    padding: 20px;
  }

  .features-grid {
    grid-template-columns: 1fr;
  }

  .stats-container {
    grid-template-columns: 1fr;
    gap: 20px;
  }
}
</style>
