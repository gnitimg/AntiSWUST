import type { RouteRecordRaw } from "vue-router"
import { createRouter } from "vue-router"
import { DASHBOARD_PATH, REDIRECT_PATH, routerConfig } from "@/router/config"
import { registerNavigationGuard } from "@/router/guard"
import { flatMultiLevelRoutes } from "./helper"

const Layouts = () => import("@/layouts/index.vue")

/** 选课页组件（五个分类共用，通过 meta.category 区分） */
const CoursePage = () => import("@/pages/course/index.vue")

/**
 * @name 常驻路由
 * @description 左侧菜单：所有选课（5 个分类）/ 我的选课 / 实验功能（抢课 + 课程组）
 */
export const constantRoutes: RouteRecordRaw[] = [
  {
    path: REDIRECT_PATH,
    component: Layouts,
    meta: {
      hidden: true
    },
    children: [
      {
        path: ":path(.*)",
        component: () => import("@/pages/redirect/index.vue")
      }
    ]
  },
  {
    path: "/403",
    component: () => import("@/pages/error/403.vue"),
    meta: {
      hidden: true
    }
  },
  {
    path: "/404",
    component: () => import("@/pages/error/404.vue"),
    meta: {
      hidden: true
    },
    alias: "/:pathMatch(.*)*"
  },
  {
    path: "/login",
    component: () => import("@/pages/login/index.vue"),
    meta: {
      hidden: true
    }
  },
  {
    path: "/",
    component: Layouts,
    redirect: DASHBOARD_PATH,
    children: [
      {
        path: "course",
        redirect: "/course/pe",
        name: "CourseAll",
        meta: {
          title: "所有选课",
          elIcon: "Menu",
          alwaysShow: true
        },
        children: [
          {
            path: "pe",
            component: CoursePage,
            name: "CoursePe",
            meta: {
              title: "体育项目",
              elIcon: "Basketball",
              category: "pe",
              keepAlive: true
            }
          },
          {
            path: "general",
            component: CoursePage,
            name: "CourseGeneral",
            meta: {
              title: "全校通选课",
              elIcon: "Collection",
              category: "general",
              keepAlive: true
            }
          },
          {
            path: "major-limited",
            component: CoursePage,
            name: "CourseMajorLimited",
            meta: {
              title: "计划课程",
              elIcon: "Notebook",
              category: "major_limited",
              keepAlive: true
            }
          },
          {
            path: "supplement",
            component: CoursePage,
            name: "CourseSupplement",
            meta: {
              title: "补选低年级课程",
              elIcon: "Reading",
              category: "supplement",
              keepAlive: true
            }
          },
          {
            path: "retake",
            component: CoursePage,
            name: "CourseRetake",
            meta: {
              title: "重新学习（重修）",
              elIcon: "RefreshLeft",
              category: "retake",
              keepAlive: true
            }
          }
        ]
      },
      {
        path: "my",
        component: () => import("@/pages/my/index.vue"),
        name: "MyCourses",
        meta: {
          title: "我的选课",
          elIcon: "Tickets",
          keepAlive: true
        }
      },
      {
        path: "lab",
        redirect: "/lab/snipe",
        name: "Lab",
        meta: {
          title: "实验功能",
          elIcon: "MagicStick",
          alwaysShow: true
        },
        children: [
          {
            path: "snipe",
            component: () => import("@/pages/snipe/index.vue"),
            name: "Snipe",
            meta: {
              title: "抢课",
              elIcon: "Aim",
              keepAlive: true
            }
          },
          {
            path: "preset",
            component: () => import("@/pages/preset/index.vue"),
            name: "PresetCourses",
            meta: {
              title: "预置选课",
              elIcon: "AlarmClock",
              keepAlive: true
            }
          },
          {
            path: "groups",
            component: () => import("@/pages/groups/index.vue"),
            name: "CourseGroups",
            meta: {
              title: "课程组",
              elIcon: "Files",
              keepAlive: true
            }
          }
        ]
      }
    ]
  }
]

/**
 * @name 动态路由
 * @description 本系统无角色权限需求，保持为空
 */
export const dynamicRoutes: RouteRecordRaw[] = []

/** 路由实例 */
export const router = createRouter({
  history: routerConfig.history,
  routes: routerConfig.thirdLevelRouteCache ? flatMultiLevelRoutes(constantRoutes) : constantRoutes
})

/** 重置路由 */
export function resetRouter() {
  try {
    router.getRoutes().forEach((route) => {
      const { name, meta } = route
      if (name && (meta.roles?.length || meta.permissions?.length)) {
        router.hasRoute(name) && router.removeRoute(name)
      }
    })
  } catch {
    location.reload()
  }
}

// 注册路由导航守卫
registerNavigationGuard(router)
