import SwiftUI

enum AppVariant {
    static let availableSections: [AppSection] = {
#if APP_PROJECTS
        return [.projects, .settings]
#elseif APP_SALES
        return [.sales, .settings]
#elseif APP_INSTALL
        return [.install, .settings]
#elseif APP_OPS
        return [.ops, .settings]
#else
        return AppSection.allCases
#endif
    }()

    static let defaultSection: AppSection = {
#if APP_PROJECTS
        return .projects
#elseif APP_SALES
        return .sales
#elseif APP_INSTALL
        return .install
#elseif APP_OPS
        return .ops
#else
        return .apps
#endif
    }()
}
